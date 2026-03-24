import { Entity, Column, PrimaryGeneratedColumn, Index } from 'typeorm';
import { Base } from '../providers/template/base.entity';

@Entity('media_resource')
export class MediaResource extends Base {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ comment: 'R2 Key' })
  @Index()
  key: string;

  @Column({ comment: 'Access URL' })
  url: string;

  @Column({ comment: 'MIME Type' })
  mimeType: string;

  @Column({ type: 'bigint', comment: 'File Size in Bytes' })
  size: number;

  @Column({ comment: 'Original Filename' })
  originalName: string;

}
