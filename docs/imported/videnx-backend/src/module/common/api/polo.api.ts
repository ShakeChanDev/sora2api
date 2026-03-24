import { Injectable, Logger, Inject } from '@nestjs/common';
import type { AxiosInstance, AxiosRequestConfig } from 'axios';
import { ThirdRecordService } from '@/src/model/third.record.service';
import { ThirdRecordStatus } from '@/src/entity/third.record.entity';
import { ThirdPartyRequest } from '@/src/common/decorators/third-party-request.decorator';


/**
 * PoloAPI 视频生成响应
 */
export interface PoloVideoResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  status: string;
  progress?: number;
  result?: {
    video_url?: string;
    error?: string;
  };
  links?: {
    mp4?: string;
    mp4_wm?: string;
    gif?: string;
    thumbnail?: string;
  };
}

/**
 * PoloAPI 创建视频请求
 */
export interface PoloCreateVideoRequest {
  image_url?: string;
  prompt: string;
  model?: string;
  remix?: string;
  style?: string;
}

/**
 * PoloAPI 任务查询响应
 */
export interface PoloTaskResponse {
  id: string;
  status: 'pending' | 'processing' | 'success' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
  created_at: number;
  completed_at?: number;
}

export interface PoloRequestOpts {
  headers?: Record<string, any>;
}

// 直接从 env 获取配置
const POLO_API_BASE_URL = process.env.POLO_API_BASE_URL || 'https://cdn.poloai.top/v1';
const POLO_API_KEY = process.env.POLO_API_KEY || '';


@Injectable()
export class PoloWebApiService {
  private readonly logger = new Logger(PoloWebApiService.name);

  @Inject('PROXY_AXIOS')
  private readonly axios: AxiosInstance;

  @Inject()
  private readonly thirdRecordService: ThirdRecordService;

  /**
   * 生成 PoloAPI 鉴权请求头
   */
  private get authHeaders(): Record<string, string> {
    if (!POLO_API_KEY) {
      return {};
    }
    return {
      'Authorization': `Bearer ${POLO_API_KEY}`,
      'Content-Type': 'application/json',
    };
  }

  /**
   * 统一请求封装（参考 dayangyu.web.api.ts 的 request 模式）
   */
  private async request<T>(
    method: 'GET' | 'POST',
    endpoint: string,
    data?: any,
    opts?: PoloRequestOpts,
  ): Promise<T> {
    if (!POLO_API_KEY) {
      throw new Error('POLO_API_KEY is not set');
    }

    const config: AxiosRequestConfig = {
      method,
      url: `${POLO_API_BASE_URL}${endpoint}`,
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
   * 创建视频任务（图生视频）
   */
  @ThirdPartyRequest({
    provider: 'polo',
    action: 'create_video',
    reqExtractor: (args) => args[0],
    keyExtractor: (res) => res?.id,
  })
  async createVideo(params: PoloCreateVideoRequest): Promise<PoloVideoResponse | null> {
    if (!params?.prompt) {
      throw new Error('createVideo missing image_url or prompt');
    }

    // 补充默认参数
    const payload = {
      image_url: params.image_url,
      prompt: params.prompt,
      model: params.model || 'sora-2-portrait-15s',
      style: params.style,
    };

    return this.request<PoloVideoResponse>('POST', '/videos', payload);
  }

  /**
   * 创建二创视频任务
   */
  @ThirdPartyRequest({
    provider: 'pollo',
    action: 'create_remix_video',
    reqExtractor: (args) => args[0],
    keyExtractor: (res) => res?.id,
  })
  async createRemixVideo(params: PoloCreateVideoRequest): Promise<PoloVideoResponse | null> {
    if (!params?.remix || !params?.prompt) {
      throw new Error('createRemixVideo missing remix_url or prompt');
    }

    return this.request<PoloVideoResponse>('POST', '/videos/remix', params);
  }

  /**
   * 查询视频任务状态
   */
  async getVideoTask(taskId: string): Promise<PoloTaskResponse | null> {
    if (!taskId) {
      this.logger.error('getVideoTask missing taskId');
      return null;
    }

    try {
      const data = await this.request<PoloTaskResponse>('GET', `/videos/generations/${encodeURIComponent(taskId)}`);

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
      this.logger.error(`Polo getVideoTask failed: ${error?.message}`, error?.response?.data);
      return null;
    }
  }
}
