"""Study endpoints: listing and sync with Orthanc."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.audit import record_event
from backend.app.deps import (
    ModelDep,
    OrthancDep,
    OverlayCacheDep,
    SessionDep,
    SettingsDep,
    StudyId,
)
from backend.app.inference import explain, load_study_image, png_bytes, predict_and_explain
from backend.app.models import Prediction, Study
from backend.app.queries import (
    latest_prediction,
    latest_predictions,
    latest_reviews,
    review_summary,
    study_or_404,
)
from backend.app.schemas import (
    NOTICE,
    PredictionOut,
    PredictionSummary,
    StudyList,
    StudyStatus,
    SyncResult,
)

router = APIRouter(prefix="/studies", tags=["studies"])


@router.get("", response_model=StudyList)
def list_studies(session: SessionDep, orthanc: OrthancDep) -> StudyList:
    """List every study in Orthanc with its status: not_synced, pending or analysed."""
    synced = set(session.scalars(select(Study.orthanc_study_id)))
    latest = latest_predictions(session)
    reviews = latest_reviews(session, [p.id for p in latest.values()])
    studies = []
    for s in orthanc.list_studies():
        oid = s["orthanc_study_id"]
        pred = latest.get(oid)
        status = "analysed" if pred else ("pending" if oid in synced else "not_synced")
        studies.append(
            StudyStatus(
                **s,
                status=status,
                latest_prediction=PredictionSummary(
                    prediction_id=pred.id,
                    probability=pred.probability,
                    label=pred.label,
                    threshold=pred.threshold,
                    created_at=pred.created_at,
                )
                if pred
                else None,
                latest_review=review_summary(reviews.get(pred.id)) if pred else None,
            )
        )
    return StudyList(count=len(studies), studies=studies)


@router.post("/sync", response_model=SyncResult)
def sync_studies(session: SessionDep, orthanc: OrthancDep) -> SyncResult:
    """Register Orthanc studies the database does not know yet; they start as pending.

    List-and-diff rather than Orthanc's changes feed: one request lists all studies, the
    diff is stateless and idempotent, and no cursor has to be stored. The cost is linear
    in the number of studies, which is fine at demo scale. ON CONFLICT DO NOTHING keeps
    concurrent syncs from creating duplicates. Studies gone from Orthanc are counted,
    never deleted.
    """
    in_orthanc = orthanc.list_studies()
    known = set(session.scalars(select(Study.orthanc_study_id)))
    added = 0
    for s in in_orthanc:
        if s["orthanc_study_id"] in known:
            continue
        result = session.execute(insert(Study).values(**s).on_conflict_do_nothing())
        if result.rowcount:
            added += 1
            record_event(
                session,
                "study_synced",
                s["study_instance_uid"],
                {"orthanc_study_id": s["orthanc_study_id"]},
            )
    session.commit()

    orthanc_ids = {s["orthanc_study_id"] for s in in_orthanc}
    all_known = set(session.scalars(select(Study.orthanc_study_id)))
    analysed = set(session.scalars(select(Prediction.orthanc_study_id).distinct()))
    return SyncResult(
        orthanc_studies=len(in_orthanc),
        added=added,
        already_synced=len(in_orthanc) - added,
        pending=len((all_known & orthanc_ids) - analysed),
        missing_from_orthanc=len(all_known - orthanc_ids),
    )


def prediction_out(session: Session, pred: Prediction, cached: bool) -> PredictionOut:
    """Response model for a stored prediction."""
    count = session.scalar(
        select(func.count(Prediction.id)).where(
            Prediction.orthanc_study_id == pred.orthanc_study_id
        )
    )
    return PredictionOut(
        prediction_id=pred.id,
        orthanc_study_id=pred.orthanc_study_id,
        study_instance_uid=pred.study_instance_uid,
        probability=pred.probability,
        label=pred.label,
        threshold=pred.threshold,
        model_name=pred.model_name,
        checkpoint_sha256=pred.checkpoint_sha256,
        created_at=pred.created_at,
        cached=cached,
        prediction_count=count,
        latest_review=review_summary(latest_reviews(session, [pred.id]).get(pred.id)),
    )


@router.post("/{orthanc_study_id}/analyse", response_model=PredictionOut)
def analyse_study(
    orthanc_study_id: StudyId,
    session: SessionDep,
    orthanc: OrthancDep,
    service: ModelDep,
    settings: SettingsDep,
    cache: OverlayCacheDep,
    force: Annotated[bool, Query(description="Re-run even if a prediction exists")] = False,
) -> PredictionOut:
    """Run the model and Grad-CAM on a synced study and store the prediction.

    Idempotent: if the study already has a prediction and force is false, the stored
    result is returned (cached=true). An audit event is written either way. With force,
    a new prediction row is added; earlier rows are never changed.
    """
    study = study_or_404(session, orthanc_study_id)
    existing = latest_prediction(session, orthanc_study_id)
    if existing is not None and not force:
        record_event(
            session,
            "analysis_returned_cached",
            study.study_instance_uid,
            {"orthanc_study_id": orthanc_study_id, "prediction_id": existing.id},
        )
        session.commit()
        return prediction_out(session, existing, cached=True)

    img = load_study_image(orthanc, study, settings.image_size)
    probability, overlay_rgb = predict_and_explain(service, img)
    pred = Prediction(
        orthanc_study_id=orthanc_study_id,
        study_instance_uid=study.study_instance_uid,
        probability=probability,
        label=int(probability >= service.threshold),
        threshold=service.threshold,
        model_name=service.model_name,
        checkpoint_sha256=service.checkpoint_sha256,
    )
    session.add(pred)
    session.flush()
    record_event(
        session,
        "analysis_completed",
        study.study_instance_uid,
        {
            "orthanc_study_id": orthanc_study_id,
            "prediction_id": pred.id,
            "probability": probability,
            "label": pred.label,
            "threshold": service.threshold,
            "model_name": service.model_name,
            "checkpoint_sha256": service.checkpoint_sha256,
            "forced": force,
        },
    )
    session.commit()
    cache.put(pred.id, png_bytes(overlay_rgb))
    return prediction_out(session, pred, cached=False)


@router.get("/{orthanc_study_id}/result", response_model=PredictionOut)
def study_result(orthanc_study_id: StudyId, session: SessionDep) -> PredictionOut:
    """The latest stored prediction for a study; 404 if the study is unknown or unanalysed."""
    study_or_404(session, orthanc_study_id)
    pred = latest_prediction(session, orthanc_study_id)
    if pred is None:
        raise HTTPException(404, detail="Study not analysed yet; call POST .../analyse")
    return prediction_out(session, pred, cached=True)


def png_response(png: bytes, extra_headers: dict[str, str] | None = None) -> Response:
    """PNG bytes built in memory, with the notice header and caching disabled."""
    headers = {"X-Notice": NOTICE, "Cache-Control": "no-store"} | (extra_headers or {})
    return Response(content=png, media_type="image/png", headers=headers)


@router.get(
    "/{orthanc_study_id}/image",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def study_image(
    orthanc_study_id: StudyId, session: SessionDep, orthanc: OrthancDep, settings: SettingsDep
) -> Response:
    """The preprocessed image the model sees (224x224 grayscale PNG), built in memory."""
    study = study_or_404(session, orthanc_study_id)
    return png_response(png_bytes(load_study_image(orthanc, study, settings.image_size)))


@router.get(
    "/{orthanc_study_id}/heatmap",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def study_heatmap(
    orthanc_study_id: StudyId,
    session: SessionDep,
    orthanc: OrthancDep,
    service: ModelDep,
    settings: SettingsDep,
    cache: OverlayCacheDep,
) -> Response:
    """Grad-CAM overlay PNG for the study's latest prediction.

    Served from the in-memory cache, or recomputed after eviction or a restart. A
    recomputed heatmap must explain the same model that made the prediction, so a
    checkpoint mismatch is refused (409) instead of silently explaining another model.
    """
    study = study_or_404(session, orthanc_study_id)
    pred = latest_prediction(session, orthanc_study_id)
    if pred is None:
        raise HTTPException(404, detail="Study not analysed yet; call POST .../analyse")
    png = cache.get(pred.id)
    source = "cache"
    if png is None:
        if pred.checkpoint_sha256 != service.checkpoint_sha256:
            raise HTTPException(
                409,
                detail="Prediction was made with a different checkpoint; re-run analyse "
                "with force=true",
            )
        png = png_bytes(explain(service, load_study_image(orthanc, study, settings.image_size)))
        cache.put(pred.id, png)
        source = "recomputed"
    return png_response(png, {"X-Prediction-Id": str(pred.id), "X-Heatmap-Source": source})
