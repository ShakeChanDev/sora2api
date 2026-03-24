import { Inject, Injectable, Logger } from '@nestjs/common';
import type { AxiosRequestConfig } from 'axios';
import FormData from 'form-data';
import { Http2Spider } from '@/src/providers/spider/http2.spider';

export interface SoraAuthParams {
  authorization?: string;
  cookie?: string;
  oaiDeviceId?: string;
  origin?: string;
  referer?: string;
  userAgent?: string;
  // ja3?: string;
}

export interface RequestOpts {
  auth?: SoraAuthParams;
  headers?: Record<string, any>;
  proxy?: false | string | {
    host: string;
    port: number;
    protocol?: string;
    auth?: { username: string; password: string };
  };
}

export interface InpaintItem {
  kind: 'file';
  file_id: string;
}

export interface CreateVideoRequest {
  kind: 'video';
  prompt: string;
  title?: string | null;
  orientation?: 'portrait' | 'landscape' | 'square';
  size?: 'small' | 'medium' | 'large';
  n_frames?: number;
  inpaint_items?: InpaintItem[];
  remix_target_id?: string | null;
  metadata?: any;
  cameo_ids?: string[] | null;
  cameo_replacements?: any;
  model?: string;
  style_id?: string | null;
  audio_caption?: string | null;
  audio_transcript?: string | null;
  video_caption?: string | null;
  storyboard_id?: string | null;
}

export interface CreateVideoResponse {
  id: string;
  priority: number;
  rate_limit_and_credit_balance?: Record<string, any>;
}

export interface PendingItem {
  id: string;
  status: string;
  prompt?: string;
  title?: string | null;
  progress_pct?: number;
  generations?: any[];
}

export interface DraftItem {
  id: string;
  kind: string;
  url?: string;
  downloadable_url?: string | null;
  download_urls?: { watermark?: string | null; no_watermark?: string | null };
  width?: number;
  height?: number;
  generation_type?: string;
  created_at?: number;
  prompt?: string;
  title?: string | null;
  encodings?: Record<string, { path: string }>;
  task_id?: string;
  generation_id?: string;
  reason?: string;
  reason_str?: string;
  markdown_reason_str?: string;
}

export interface UploadFileResponse {
  asset_pointer: string;
  file_id: string;
  url: string;
  size: number;
  azure_asset_pointer: string | null;
  contains_realistic_person: boolean;
}

export interface ShareVideoResponse {
  post: {
    id: string;
    permalink: string;
    // ... other fields if needed
  };
}

export interface DraftsResponse {
  items: DraftItem[];
  cursor: string | null;
}

@Injectable()
export class SoraWebApiService {
  private readonly logger = new Logger(SoraWebApiService.name);
  private readonly baseUrl = 'https://sora.chatgpt.com';

  // @Inject(GotSpider) private readonly http2Spider: GotSpider;
  @Inject(Http2Spider) private readonly http2Spider: Http2Spider;

  private getDefaultHeaders(auth?: SoraAuthParams, appendHeaders: Record<string, any> = {}) {
    const base: Record<string, any> = {
      Accept: '*/*',
      'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6',
      'Sec-Fetch-Dest': 'empty',
      'Sec-Fetch-Mode': 'cors',
      'Sec-Fetch-Site': 'same-origin',
      Pragma: 'no-cache',
      'Cache-Control': 'no-cache',
      Priority: 'u=1, i',
      'Content-Type': 'application/json',
      Origin: this.baseUrl,
      Referer: `${this.baseUrl}/explore`,
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    };
    const merged = {
      ...base,
      ...(auth?.authorization ? { Authorization: auth.authorization } : {}),
      ...(auth?.cookie ? { Cookie: auth.cookie } : {}),
      ...(auth?.oaiDeviceId ? { 'oai-device-id': auth.oaiDeviceId } : {}),
      // ...(auth?.sentinelToken ? { 'openai-sentinel-token': auth.sentinelToken } : {}),
      ...(auth?.origin ? { Origin: auth.origin } : {}),
      ...(auth?.referer ? { Referer: auth.referer } : {}),
      ...(auth?.userAgent ? { 'User-Agent': auth.userAgent } : {}),
      // ...(auth?.ja3 ? { ja3: auth.ja3 } : {}),
      ...appendHeaders,
    };
    return merged;
  }

  private async request<T>(
    method: 'GET' | 'POST',
    endpoint: string,
    data?: any,
    opts?: RequestOpts,
  ): Promise<T> {
    const config: AxiosRequestConfig = {
      method,
      url: `${this.baseUrl}${endpoint}`,
      headers: this.getDefaultHeaders(opts?.auth, opts?.headers || {}),
    };

    if (opts && 'proxy' in opts) {
      (config as any).proxy = opts.proxy as any;
    }

    if (method === 'GET') {
      config.params = data;
    } else {
      config.data = data;
    }

    const response = await this.http2Spider.request<T>(config);
    return (response as any).data as any;
  }

  async createVideo(payload: CreateVideoRequest, opts?: RequestOpts): Promise<CreateVideoResponse> {
    const normalized: CreateVideoRequest = {
      kind: 'video',
      prompt: payload.prompt,
      title: payload.title ?? null,
      orientation: payload.orientation ?? 'portrait',
      size: payload.size ?? 'small',
      n_frames: payload.n_frames ?? 300,
      inpaint_items: payload.inpaint_items ?? [],
      remix_target_id: payload.remix_target_id ?? null,
      metadata: payload.metadata ?? null,
      cameo_ids: payload.cameo_ids ?? null,
      cameo_replacements: payload.cameo_replacements ?? null,
      model: payload.model ?? 'sy_8',
      style_id: payload.style_id ?? null,
      audio_caption: payload.audio_caption ?? null,
      audio_transcript: payload.audio_transcript ?? null,
      video_caption: payload.video_caption ?? null,
      storyboard_id: payload.storyboard_id ?? null,
    };
    return this.request<CreateVideoResponse>('POST', '/backend/nf/create', normalized, opts);
  }

  async uploadFile(file: Buffer, filename: string, opts?: RequestOpts): Promise<UploadFileResponse> {
    try {
      const form = new FormData();
      form.append('use_case', 'inpaint_safe');
      form.append('file', file, { filename });

      // Note: We are relying on Http2Spider to handle FormData serialization
      return this.request<UploadFileResponse>('POST', '/backend/project_y/file/upload', form, {
          ...opts,
          headers: {
              ...opts?.headers,
              // Let FormData generate the boundary
              ...form.getHeaders()
          }
      });
    } catch (e) {
      this.logger.error(`Upload execution failed: ${e.message}`);
      throw e;
    }
  }

  async shareVideo(generationId: string, opts?: RequestOpts): Promise<ShareVideoResponse> {
    const payload = {
      attachments_to_create: [
        {
          generation_id: generationId,
          kind: 'sora',
        },
      ],
      post_text: '',
    };
    return this.request<ShareVideoResponse>('POST', '/backend/project_y/post', payload, opts);
  }

  async getPending(opts?: RequestOpts): Promise<PendingItem[]> {
    return this.request<PendingItem[]>('GET', '/backend/nf/pending/v2', undefined, opts);
  }

  async getDrafts(params: { limit?: number }, opts?: RequestOpts): Promise<DraftsResponse> {
    return this.request<DraftsResponse>('GET', '/backend/project_y/profile/drafts', params, opts);
  }

  /**
   * Check if proxy is available by accessing Sora homepage
   */
  async checkProxy(opts?: RequestOpts): Promise<boolean> {
      try {
          await this.request('GET', '', undefined, opts);
          return true;
      } catch (e) {
          this.logger.warn(`Proxy check failed: ${e.message}`);
          return false;
      }
  }
}
