/**
 * Checks the hand-written API types against the committed backend schema (docs/openapi.json),
 * so a backend change that is not reflected here fails the frontend tests.
 */
import { describe, expect, it } from 'vitest'
import openapiJson from '../../../docs/openapi.json'
import { NOTICE } from '../notice'
import { ENDPOINTS } from './client'
import {
  DECISIONS,
  EVENT_TYPES,
  FREE_TEXT_MAX,
  REVIEWER_MAX,
  SCHEMA_FIELDS,
  STUDY_STATUSES,
} from './types'

interface Prop {
  type?: string
  $ref?: string
  anyOf?: Prop[]
  enum?: string[]
  maxLength?: number
}
interface Schema {
  properties: Record<string, Prop>
  required?: string[]
}
interface Operation {
  parameters?: { name: string; schema: Prop }[]
}
const spec = openapiJson as unknown as {
  info: { description: string }
  paths: Record<string, Record<string, Operation>>
  components: { schemas: Record<string, Schema> }
}
const schemas = spec.components.schemas

function kind(p: Prop): string {
  if (p.$ref) return 'object'
  if (p.type === 'integer') return 'number'
  return p.type ?? 'unknown'
}

/** The same notation as FieldSpec in types.ts: kind, `?` if not required, `|null`. */
function describeProp(p: Prop, required: boolean): string {
  const variants = p.anyOf ?? [p]
  const nonNull = variants.filter((v) => v.type !== 'null')
  const kinds = [...new Set(nonNull.map(kind))]
  const nullable = nonNull.length < variants.length
  return `${kinds.join('/')}${required ? '' : '?'}${nullable ? '|null' : ''}`
}

describe('API types match docs/openapi.json', () => {
  it('has a field table for every schema except the untyped ValidationError', () => {
    const fromSpec = Object.keys(schemas).filter((n) => n !== 'ValidationError')
    expect(Object.keys(SCHEMA_FIELDS).sort()).toEqual(fromSpec.sort())
  })

  it.each(Object.entries(SCHEMA_FIELDS))('%s fields, optionality and nullability', (name, fields) => {
    const schema = schemas[name]
    expect(schema).toBeDefined()
    const expected = Object.fromEntries(
      Object.entries(schema!.properties).map(([field, prop]) => [
        field,
        describeProp(prop, schema!.required?.includes(field) ?? false),
      ]),
    )
    expect(fields).toEqual(expected)
  })

  it('lists exactly the endpoints in the schema', () => {
    const fromSpec = Object.entries(spec.paths).flatMap(([path, ops]) =>
      Object.keys(ops).map((method) => `${method.toUpperCase()} ${path}`),
    )
    expect([...ENDPOINTS].sort()).toEqual(fromSpec.sort())
  })

  it('uses the same enum values', () => {
    expect(schemas.StudyStatus!.properties.status!.enum).toEqual([...STUDY_STATUSES])
    expect(schemas.ReviewIn!.properties.decision!.enum).toEqual([...DECISIONS])
    expect(schemas.ReviewOut!.properties.decision!.enum).toEqual([...DECISIONS])
    const eventParam = spec.paths['/audit']!.get!.parameters!.find((p) => p.name === 'event_type')
    expect(eventParam!.schema.anyOf![0]!.enum).toEqual([...EVENT_TYPES])
  })

  it('uses the same free-text length limits', () => {
    const review = schemas.ReviewIn!.properties
    expect(review.reviewer!.maxLength).toBe(REVIEWER_MAX)
    expect(review.reason!.anyOf![0]!.maxLength).toBe(FREE_TEXT_MAX)
    expect(review.comment!.anyOf![0]!.maxLength).toBe(FREE_TEXT_MAX)
  })

  it('shows the same notice as the API', () => {
    expect(NOTICE).toBe(spec.info.description)
  })
})
