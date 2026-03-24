import { Injectable, Inject, Logger } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { In, Repository } from 'typeorm';
import { IVideoTaskRunner } from './video.runner.interface';
import { Task, TaskPayload, TaskStatus, TaskType } from '@/src/entity/task.entity';
import { TaskGenerateType, TaskGroup, TaskGroupStage } from '@/src/entity/task-group.entity';
import { AnalysisRecord, AnalysisResult } from '@/src/entity/analysis-record.entity';
import { PureEngineService } from '@/src/providers/template/engine.service';
import { Prompt, PromptConfigType, PromptStatus, PromptContentByType } from '@/src/entity/prompt.entity';
import { AiGroupAgentService } from '@/src/module/common/agent/ai-group.agent.service';

@Injectable()
export class GroupVideoRunner extends PureEngineService implements IVideoTaskRunner {
  private readonly logger = new Logger(GroupVideoRunner.name);

  @InjectRepository(Task)
  private readonly taskRepo: Repository<Task>;

  @InjectRepository(TaskGroup)
  private readonly groupRepo: Repository<TaskGroup>;

  @InjectRepository(Prompt)
  private readonly promptRepo: Repository<Prompt>;

  @InjectRepository(AnalysisRecord)
  private readonly analysisRepo: Repository<AnalysisRecord>;

  @Inject()
  private readonly aiGroupAgent: AiGroupAgentService;

  /**
   * 扫描待处理任务并生成任务分组
   */
  async run(): Promise<void> {
    const tasks = await this.taskRepo.find({
      where: { status: TaskStatus.PENDING },
      take: 10,
    });

    for (const task of tasks) {
      try {
        await this.processTask(task);
      } catch (error) {
        this.logger.error(`Failed to process task ${task.id}: ${error.message}`, error.stack);
        task.status = TaskStatus.FAILED;
        task.error = error?.message || '任务处理失败';
        await this.taskRepo.save(task);
      }
    }
  }

  /**
   * 根据任务负载创建对应的 TaskGroup
   */
  private async processTask(task: Task): Promise<void> {
    this.logger.log(`Processing Task: ${task.id}`);

    const existingGroups = await this.groupRepo.count({ where: { taskId: task.id } });
    if (existingGroups > 0) {
      return;
    }

    task.status = TaskStatus.PROCESSING;
    task.error = '';
    await this.taskRepo.save(task);

    const payload = (task.payload ?? {}) as TaskPayload;
    
    // 直接从 task.type 推断 generateType（单一数据源）
    const generateType: TaskGenerateType = task.type === 'remix' ? TaskGenerateType.REMIX : TaskGenerateType.IMAGE;
    
    const basePrompt = payload.prompt ?? '';
    const baseConfig = Object.assign({
      duration: 15,
    }, payload.config);
    const baseCount = Math.max(1, Math.floor(Number(payload.count ?? 1)));
    const baseReference = this.getTaskReferences(payload, generateType);

    // 检查任务类型
    const groupMode = task.type === TaskType.AIGROUP;
    const replicationMode = task.type === TaskType.REPLICATION;
    
    let promptItems: string[] = [];
    if (replicationMode) {
      // 复刻任务：加载策略对象作为提示词，走 AiGroup 流程
      const strategyResult = await this.loadReplicationStrategy(task);
      const replicationPayload: TaskPayload = {
        ...payload,
        prompt: JSON.stringify(strategyResult),
      };
      promptItems = await this.buildAiGroupPromptList(replicationPayload, generateType);
    } else if (groupMode) {
      promptItems = await this.buildAiGroupPromptList(payload, generateType);
    } else {
      // Image 模式：拼接 basePrompt + 环境提示词，包装为 Standard JSON
      const envPrompts = await this.resolveEnvPrompts(payload);
      const meta = this.buildPromptMeta(payload);
      const combined = [...envPrompts, basePrompt].filter(Boolean).join('\n\n');
      promptItems = combined ? [this.wrapPromptWithMeta(combined, meta)] : [];
    }
    
    const groupCount = (groupMode || replicationMode)
      ? Math.max(1, Math.floor(Number((payload as any).groupCount ?? (promptItems.length || 1))))
      : 1;
    const stage = (groupMode || replicationMode) ? TaskGroupStage.WAITING_CONFIRM : TaskGroupStage.QUEUED;

    const groups: TaskGroup[] = [];
    const totalGroups = (groupMode || replicationMode) ? promptItems.length : groupCount;
    for (let i = 0; i < totalGroups; i++) {
      const prompt = promptItems[i] ?? basePrompt;
      groups.push(
        this.groupRepo.create({
          taskId: task.id,
          generateType: generateType,
          prompt,
          reference: baseReference,
          config: baseConfig,
          targetCount: baseCount,
          stage,
          operatorUserId: task.operatorUserId,
        }),
      );
    }

    await this.groupRepo.save(groups);
    this.logger.log(`Created TaskGroup for Task ${task.id}`);
  }

  private async buildAiGroupPromptList(payload: TaskPayload, generateType: TaskGenerateType): Promise<string[]> {
    const baseInput = payload.prompt ?? '';
    const envPrompts = await this.resolveEnvPrompts(payload);
    const meta = this.buildPromptMeta(payload);
    const groupCount = Math.max(1, Math.floor(Number((payload as any).groupCount ?? 1)));
    const reference = this.getTaskReferences(payload, generateType); // 获取筛选后的图片引用
    try {
      const rawPrompts = await this.aiGroupAgent.buildGroupPrompts(baseInput, {
        envPrompts,
        groupCount,
        reference, // 传递 reference 参数
      });
      return rawPrompts.map((p) => this.wrapPromptWithMeta(p, meta));
    } catch (error) {
      this.logger.error(`AiGroup plan failed: ${error.message}`, error.stack);
    }
    throw new Error('AI 分组失败');
  }

  /**
   * 从 AnalysisRecord 加载复刻策略（分析已在独立的 /analysis/strategies 接口完成）
   */
  private async loadReplicationStrategy(task: Task): Promise<{ strategies: AnalysisResult }> {
    const analysisId = task.analysisId;
    if (!analysisId) {
      throw new Error('复刻任务缺少 analysisId，请先调用分析接口');
    }

    const analysisRecord = await this.analysisRepo.findOne({
      where: { id: analysisId },
    });

    if (!analysisRecord) {
      throw new Error(`分析记录不存在: ${analysisId}`);
    }

    const result = analysisRecord.result;
    if (!result?.length) {
      throw new Error('分析记录中没有有效的策略数据');
    }

    this.logger.log(`Loaded ${result.length} strategies from AnalysisRecord ${analysisId}`);
    return { strategies: result };
  }

  /**
   * 获取任务引用资源（合并了原有逻辑和图片筛选逻辑）
   */
  private getTaskReferences(payload: TaskPayload, generateType: TaskGenerateType) {
    const baseReference =
      generateType === TaskGenerateType.REMIX
        ? [{ type: 'remix', url: generateType === TaskGenerateType.REMIX && 'linkUrl' in payload ? payload.linkUrl ?? '' : '' }]
        : payload.reference ?? [];

    return baseReference.filter((item) => item.type === 'image' && item.url);
  }

  /**
   * 根据 promptlistKey 拉取激活的环境提示词内容
   */
  private async resolveEnvPrompts(payload: TaskPayload): Promise<string[]> {
    const promptIds = Array.isArray((payload).promptlistKey)
      ? (payload).promptlistKey.filter(Boolean)
      : [];
    if (!promptIds.length) return [];
    
    const presets = await this.promptRepo.find({
      where: { id: In(promptIds), status: PromptStatus.ACTIVE },
    });
    return presets
      .map((preset) => {
        const content = (preset?.content ?? {}) as PromptContentByType[PromptConfigType.VIDEO_SCENE];
        return JSON.stringify(content);
      })
      .filter(Boolean);
  }

  /**
   * 构建 meta 对象，目前包含 Language
   */
  private buildPromptMeta(payload: TaskPayload): { Language: string } | undefined {
    const lang = payload.language?.trim();
    return lang ? { Language: lang } : undefined;
  }

  /**
   * 将 prompt 内容包装为 Standard JSON 格式 { meta, storyboard }
   */
  private wrapPromptWithMeta(content: string, meta?: { Language: string }): string {
    const storyboard = this.parsePromptContent(content);
    
    // 构造最终对象
    const result: Record<string, unknown> = {};
    if (meta) {
      result.meta = meta;
    }
    result.storyboard = storyboard;
    
    return JSON.stringify(result);
  }

  /**
   * 尝试解析内容为 JSON 对象/数组，失败则作为普通字符串放入数组
   */
  private parsePromptContent(content: string): unknown[] {
    try {
      const parsed = JSON.parse(content);
      // 如果解析出来是数组，直接用
      if (Array.isArray(parsed)) return parsed;
      // 如果是对象，包装进数组
      return [parsed];
    } catch {
      // 解析失败，视为纯文本，包装进数组
      return [content];
    }
  }

}


