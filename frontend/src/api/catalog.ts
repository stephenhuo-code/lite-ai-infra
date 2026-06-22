// 元数据目录(Gravitino Catalog Explorer · ADR-016)层级端点。
// 端点/返回形态以契约 contracts/openapi/metadata.yaml + 生成类型 types-metadata.ts 为准:
//   GET /v1/catalogs                              → NameList { names }
//   GET /v1/catalogs/{c}/schemas                  → NameList { names }
//   GET /v1/catalogs/{c}/schemas/{s}/datasets     → DatasetList { datasets }
// metadata-service 按企业/组 can() 过滤,只返回有权访问的项(只读浏览/发现视图)。
import { api } from './client'
import type { components } from './types-metadata'

export type NameList = components['schemas']['NameList']
export type DatasetList = components['schemas']['DatasetList']
export type Dataset = components['schemas']['Dataset']

export const listCatalogs = () =>
  api.get('/v1/catalogs') as Promise<NameList>

export const listSchemas = (c: string) =>
  api.get(`/v1/catalogs/${c}/schemas`) as Promise<NameList>

export const listDatasets = (c: string, s: string) =>
  api.get(`/v1/catalogs/${c}/schemas/${s}/datasets`) as Promise<DatasetList>
