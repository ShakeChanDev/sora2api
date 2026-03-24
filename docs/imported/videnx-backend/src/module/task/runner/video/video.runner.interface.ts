import { Task } from '@/src/entity/task.entity';
import { VideoArtifact } from '@/src/entity/video-artifact.entity';

export interface IVideoTaskRunner {
  run(): Promise<void>;
}

export interface IVideoRunnerContext {
  task?: Task;
  artifact?: VideoArtifact;
}
