// 接口响应类型定义
export interface BaseApiResponse<T = any> {
  code: number;
  message: string;
  status?: number;
  data: T;
}