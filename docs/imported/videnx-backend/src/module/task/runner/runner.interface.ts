import { VideoArtifact } from '@/src/entity/video-artifact.entity';

export interface RunnerInput {
  type?: string; // image | remix
  prompt?: string;
  count?: number; // 生成数量
  linkUrl?: string; // remix 二创输入（URL 或 ID）
  config?: {
    duration?: number; // 视频时长(秒)
    model?: string;
    ratio?: string; // 视频比例
  };
  reference?: {
    url: string;
    type: string; // 'image' | 'video'
  }[];
}

export interface RunnerOutput {
  [key: string]: any;
}

export interface VideoInput {
  // Deprecated: Use flattened RunnerInput structure instead
  count?: number; 
  duration?: number; 
  model?: string;
  reference?: {
    url: string;
    type: string; 
  }[];
}

export interface ResourceGroup {
  preImg?: string;
  videos?: string[];
  prompts?: string[];
  images?: string[];
  [key: string]: any;
}

export interface GenerateVideoOutput extends RunnerOutput {
  type: string;
  videos: VideoArtifact[];
}
