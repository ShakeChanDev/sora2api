import { Injectable, Inject, Logger } from '@nestjs/common';
import type { AxiosInstance, AxiosRequestConfig } from 'axios';
import { ThirdRecordService } from '@/src/model/third.record.service';
import { ThirdRecordStatus } from '@/src/entity/third.record.entity';
import { ThirdPartyRequest } from '@/src/common/decorators/third-party-request.decorator';


export interface SorarpaCreateVideoByUrlRequest {
  prompt: string;
  image_url?: string;
  model?: string;
}

export interface SorarpaRemixVideoRequest {
  prompt: string;
  model: string;
  remix: string;
  style?: string;
  image_url?: string;
  storyboard?: boolean;
  trim?: boolean;
}

export interface SorarpaCreateVideoResponse {
  id: number;
  status: string;
  message: string;
}

export interface SorarpaVideoTaskResponse {
  id: string;
  object: string;
  status: string;
  progress: number;
  progress_message: string | null;
  created_at: number;
  video_url?: string;
  completed_at?: number;
  prompt: string;
}

export interface RoleOwnerProfile {
  username: string;
}

export interface SorarpaRoleResponse {
  user_id: string;
  username: string;
  display_name: string;
  permalink: string;
  profile_picture_url: string | null;
  likes_received_count: number;
  cameo_count: number;
  created_at: number;
  updated_at: number;
  banned_at: number | null;
  description: string | null;
  owner_profile: RoleOwnerProfile | null;
}

export interface SorarpaRequestOpts {
  headers?: Record<string, any>;
}

@Injectable()
export class SorarpaWebApiService {
  private readonly logger = new Logger(SorarpaWebApiService.name);
  private readonly baseUrl = 'https://www.zzrj.fun:58000';

  @Inject('PROXY_AXIOS')
  private readonly axios: AxiosInstance;

  @Inject()
  private readonly thirdRecordService: ThirdRecordService;

  /**
   * 获取 Sorarpa API Key（来自环境变量）
   */
  private get apiKey(): string {
    return process.env.SORARPA_API_KEY || '';
  }

  /**
   * 生成 Sorarpa 鉴权请求头
   */
  private get authHeaders(): Record<string, string> {
    if (!this.apiKey) {
      return {};
    }
    return {
      Authorization: `Bearer ${this.apiKey}`,
      'Content-Type': 'application/json',
    };
  }

  /**
   * 统一请求封装（参考 sora.web.api.ts 的 request 模式）
   */
  private async request<T>(
    method: 'GET' | 'POST',
    endpoint: string,
    data?: any,
    opts?: SorarpaRequestOpts,
  ): Promise<T> {
    if (!this.apiKey) {
      throw new Error('SORARPA_API_KEY is not set');
    }

    const config: AxiosRequestConfig = {
      method,
      url: `${this.baseUrl}${endpoint}`,
      headers: {
        ...this.authHeaders,
        ...(opts?.headers || {}),
      },
    };

    if (method === 'GET') {
      config.params = data;
    } else {
      config.data = data;
    }

    const response = await this.axios.request<T>(config);
    return response.data;
  }

  /**
   * 通过图片 URL 创建视频任务
   */
  @ThirdPartyRequest({
    provider: 'sorarpa',
    action: 'create_video',
    reqExtractor: (args) => args[0],
    keyExtractor: (res) => res?.id?.toString(),
  })
  async createVideoByUrl(params: SorarpaCreateVideoByUrlRequest): Promise<SorarpaCreateVideoResponse | null> {
    if (!params?.image_url && !params?.prompt) {
      throw new Error('createVideoByUrl missing image_url or prompt');
    }
    const payload = {
      image: params.image_url,
      prompt: params.prompt,
      model: params.model,
    };
    return this.request<SorarpaCreateVideoResponse>('POST', '/v1/videos', payload);
  }

  /**
   * 通过 remix 任务ID/作品ID 创建二创视频任务
   */
  @ThirdPartyRequest({
    provider: 'sorarpa',
    action: 'create_remix_video',
    reqExtractor: (args) => args[0],
    keyExtractor: (res) => res?.id?.toString(),
  })
  async createRemixVideo(params: SorarpaRemixVideoRequest): Promise<SorarpaCreateVideoResponse | null> {
    if (!params?.remix || !params?.prompt || !params?.model) {
      throw new Error('createRemixVideo missing remix or prompt or model');
    }
    return this.request<SorarpaCreateVideoResponse>('POST', '/v1/videos', params);
  }

  /**
   * 查询视频任务状态
   */
  async getVideoTask(taskId: string): Promise<SorarpaVideoTaskResponse | null> {
    if (!taskId) {
      this.logger.error('getVideoTask missing taskId');
      return null;
    }

    try {
      const data = await this.request<SorarpaVideoTaskResponse>('GET', `/v1/videos/${encodeURIComponent(taskId)}`);

      if (data?.video_url) {
        // 使用新的 finish 方法 (支持 ID 或 RequestKey)
        await this.thirdRecordService.finish(taskId, {
          status: ThirdRecordStatus.SUCCESS,
          response: data as any,
          responseAt: new Date(),
        });
      } else if (data?.status === 'failed') {
        await this.thirdRecordService.finish(taskId, {
          status: ThirdRecordStatus.FAILED,
          response: data as any,
          error: (data as any).message || (data as any).error_message || 'Task failed on platform',
          responseAt: new Date(),
        });
      }
      return data;
    } catch (error: any) {
      this.logger.error(`Sorarpa getVideoTask failed: ${error?.message}`, error?.response?.data);
      // Optional: Log failure in records too? 
      // Current design only logs success finish when URL is ready.
      return null;
    }
  }

  /**
   * 按 username 抓取角色公开资料
   */
  @ThirdPartyRequest({
    provider: 'sorarpa',
    action: 'get_role',
    reqExtractor: (args) => args[0],
    // keyExtractor: (res) => res?.username,
  })
  async getRoleByUsername(username: string): Promise<SorarpaRoleResponse | null> {
    if (!username) {
      return null;
    }
    return this.request<SorarpaRoleResponse>('GET', `/v1/roles/${encodeURIComponent(username)}`);
  }
}
