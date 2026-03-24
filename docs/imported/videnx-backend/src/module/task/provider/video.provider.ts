import { Injectable, Inject } from '@nestjs/common';
import { SorarpaWebApiService } from '@/src/module/common/api/sorarpa.api';
import { PoloWebApiService } from '@/src/module/common/api/polo.api';
import { DayangyuWebApiService } from '@/src/module/common/api/dayangyu.web.api';

// 供应商列表（优先级从高到低）
const PROVIDERS = ['sorarpa', 'polo', 'dayangyu'] as const;
export type ProviderType = typeof PROVIDERS[number];

// 用户需求输入
export interface VideoCreateReq {
  imageUrl?: string;
  remixUrl?: string;
  prompt: string;
  duration?: number; // 15 或 60 秒
}

// 统一创建输出
export interface CreateResult {
  platform: ProviderType;
  platformTaskId: string;
}

// 统一查询输出
export interface PollResult {
  status: 'pending' | 'processing' | 'success' | 'failed';
  videoUrl?: string;
  errorMsg?: string;
}

@Injectable()
export class VideoProvider {
  public readonly maxAttempts = PROVIDERS.length * 2;

  @Inject()
  private readonly sorarpaApi: SorarpaWebApiService;

  @Inject()
  private readonly poloApi: PoloWebApiService;

  @Inject()
  private readonly dayangyuApi: DayangyuWebApiService;

  /** 根据尝试次数获取供应商 */
  getProviderByAttempt(attempt: number): ProviderType {
    return PROVIDERS[attempt % PROVIDERS.length];
  }

  /** 创建视频 */
  async create(req: VideoCreateReq, provider: ProviderType): Promise<CreateResult> {
    const model = req.duration === 15 ? 'sora2-portrait-15s' : 'sora2-portrait';
    let defaultParams = {
      model,
      remix: req.remixUrl,
      prompt: req.prompt,
      image_url: req.imageUrl,
    };


    const fnMap: Record<ProviderType, () => Promise<CreateResult>> = {
      sorarpa: async () => {
        const resp = req.remixUrl 
          ? await this.sorarpaApi.createRemixVideo(defaultParams) 
          : await this.sorarpaApi.createVideoByUrl(defaultParams );
        return { platform: 'sorarpa', platformTaskId: resp?.id?.toString() || '' };
      },
      dayangyu: async () => {
        const resp = req.remixUrl ? await this.dayangyuApi.createRemixVideo(defaultParams) : await this.dayangyuApi.createVideoByUrl(defaultParams);
        return { platform: 'dayangyu', platformTaskId: resp?.id || '' };
      },
      polo: async () => {
        const resp = req.remixUrl ? await this.poloApi.createRemixVideo(defaultParams) : await this.poloApi.createVideo(defaultParams);
        return { platform: 'polo', platformTaskId: resp?.id || '' };
      },
    };
    return fnMap[provider]();
  }

  /** 查询任务状态 */
  async poll(taskId: string, provider: ProviderType): Promise<PollResult> {
    let resp;
    if (provider === 'sorarpa') {
      resp = await this.sorarpaApi.getVideoTask(taskId);
    } else if (provider === 'dayangyu') {
      resp = await this.dayangyuApi.getVideoTask(taskId);
    } else {
      resp = await this.poloApi.getVideoTask(taskId);
    }

    if (!resp) return { status: 'failed', errorMsg: 'No response' };
    return {
      status: resp.status === 'success' ? 'success' : resp.status === 'failed' ? 'failed' : 'processing',
      videoUrl: resp.video_url,
      errorMsg: (resp as any).error_message || (resp as any).error || undefined,
    };
  }
}
