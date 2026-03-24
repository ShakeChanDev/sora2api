import { Injectable, Inject, Logger } from '@nestjs/common';
import type { AxiosInstance, AxiosRequestConfig } from 'axios';
import { ThirdRecordService } from '@/src/model/third.record.service';
import { ThirdRecordStatus } from '@/src/entity/third.record.entity';
import { ThirdPartyRequest } from '@/src/common/decorators/third-party-request.decorator';

export interface DayangyuResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: Array<{
    finish_reason: string;
    index: number;
    message: {
      role: string;
      content: string;
    };
  }>;
  links: {
    gif?: string;
    text?: string;
    id?: string;
    mp4?: string;
    mp4_wm?: string;
    md?: string;
    thumbnail?: string;
  };
}

export interface DayangyuCreateVideoByUrlRequest {
  image_url: string;
  prompt: string;
  model?: string;
}

export interface DayangyuRemixVideoRequest {
  prompt: string;
  model: string;
  remix: string;
  style?: string;
  image_url?: string;
  storyboard?: boolean;
  trim?: boolean;
}

export interface DayangyuCreateVideoResponse {
  id: string;
  object: string;
  model: string;
  status: string;
  progress: number;
  created_at: number;
  size?: string;
}

export interface DayangyuVideoTaskResponse {
  id: string;
  object: string;
  model: string;
  status: string;
  progress: number;
  created_at: number;
  completed_at?: number;
  size?: string;
  video_url?: string;
}

export interface DayangyuRequestOpts {
  headers?: Record<string, any>;
}

@Injectable()
export class DayangyuWebApiService {
  private readonly logger = new Logger(DayangyuWebApiService.name);
  private readonly baseUrl = 'https://api.dyuapi.com';

  @Inject('PROXY_AXIOS')
  private readonly axios: AxiosInstance;

  @Inject()
  private readonly thirdRecordService: ThirdRecordService;

  /**
   * 获取 Dayangyu API Key（来自环境变量）
   */
  private get apiKey(): string {
    return process.env.DAYANGYU_API_KEY || '';
  }

  /**
   * 生成 Dayangyu 鉴权请求头
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
    opts?: DayangyuRequestOpts,
  ): Promise<T> {
    if (!this.apiKey) {
      throw new Error('DAYANGYU_API_KEY is not set');
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
    provider: 'dayangyu',
    action: 'create_video',
    reqExtractor: (args) => args[0],
    keyExtractor: (res) => res?.id,
  })
  async createVideoByUrl(params: DayangyuCreateVideoByUrlRequest): Promise<DayangyuCreateVideoResponse | null> {
    if (!params?.image_url && !params?.prompt) {
      throw new Error('createVideoByUrl missing image_url or prompt');
    }
    return this.request<DayangyuCreateVideoResponse>('POST', '/v1/videos', params);
  }

  /**
   * 通过 remix 任务ID/作品ID 创建二创视频任务
   */
  @ThirdPartyRequest({
    provider: 'dayangyu',
    action: 'create_remix_video',
    reqExtractor: (args) => args[0],
    keyExtractor: (res) => res?.id,
  })
  async createRemixVideo(params: DayangyuRemixVideoRequest): Promise<DayangyuCreateVideoResponse | null> {
    if (!params?.remix || !params?.prompt || !params?.model) {
      throw new Error('createRemixVideo missing remix or prompt or model');
    }
    return this.request<DayangyuCreateVideoResponse>('POST', '/v1/videos', params);
  }

  /**
   * 查询视频任务状态
   */
  async getVideoTask(taskId: string): Promise<DayangyuVideoTaskResponse | null> {
    if (!taskId) {
      this.logger.error('getVideoTask missing taskId');
      return null;
    }

    try {
      const data = await this.request<DayangyuVideoTaskResponse>('GET', `/v1/videos/${encodeURIComponent(taskId)}`);
      
      if (data?.video_url) {
        // 使用新的 finish 方法 (支持 ID 或 RequestKey)
        await this.thirdRecordService.finish(taskId, {
          status: ThirdRecordStatus.SUCCESS,
          response: data as any,
          responseAt: new Date(),
        });
      }
      return data;
    } catch (error: any) {
      this.logger.error(`Dayangyu getVideoTask failed: ${error?.message}`, error?.response?.data);
      // Optional: Log failure in records too? 
      // Current design only logs success finish when URL is ready.
      return null;
    }
  }

  /**
   * 去除 Sora 分享链接水印，返回无水印视频地址
   */
  async removeWatermark(soraUrl: string): Promise<string | null> {
    const data = await this.request<DayangyuResponse>(
      'POST',
      '/v1/chat/completions',
      {
        model: 'sora_url',
        messages: [
          {
            role: 'user',
            content: soraUrl,
          },
        ],
      },
    );

    if (data?.links?.mp4) {
      return data.links.mp4;
    }

    this.logger.warn(`No mp4 link found in response for ${soraUrl}`);
    return null;
  }
}
