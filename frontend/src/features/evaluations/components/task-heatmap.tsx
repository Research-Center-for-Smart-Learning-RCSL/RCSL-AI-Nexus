'use client';

import { useState } from 'react';

import { cn } from '@/lib/utils';
import { heatmapGrid } from '@/components/composed/chart-geometry';
import {
  VERDICT_LABELS,
  formatScore,
  indexTaskScores,
  shortModelLabel,
  taskKey,
  taskOrder,
  type EvaluationReport,
  type TaskVerdict,
} from '@/features/evaluations/schema';

const CELL_H = 22;
const CELL_GAP = 2;
const LABEL_W = 140;
const MODEL_HEADER_H = 28;
const VERDICT_W = 16;

const VERDICT_DOT: Record<TaskVerdict, string> = {
  discriminates: 'fill-primary',
  undecided: 'fill-amber-500/60',
  saturated_high: 'fill-muted-foreground/30',
  saturated_low: 'fill-destructive/60',
};

export function TaskHeatmap({ report }: { report: EvaluationReport }) {
  const allTasks = taskOrder(report);
  const [showSaturated, setShowSaturated] = useState(false);

  const signalTasks = allTasks.filter((t) => {
    const v = report.verdicts[t.task];
    return v === 'discriminates' || v === 'undecided';
  });
  const saturatedTasks = allTasks.filter((t) => {
    const v = report.verdicts[t.task];
    return v === 'saturated_high' || v === 'saturated_low';
  });

  const tasks = showSaturated ? allTasks : signalTasks;
  const models = report.models;
  const scores = indexTaskScores(report);

  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);

  if (tasks.length === 0 || models.length === 0) return null;

  const cellW = Math.max(24, Math.min(60, (640 - LABEL_W - VERDICT_W) / models.length));
  const gridW = cellW * models.length + CELL_GAP * (models.length - 1);
  const gridH = CELL_H * tasks.length + CELL_GAP * (tasks.length - 1);
  const totalW = LABEL_W + gridW + CELL_GAP + VERDICT_W;
  const totalH = MODEL_HEADER_H + gridH;

  const cells = heatmapGrid(tasks.length, models.length, {
    x0: LABEL_W,
    y0: MODEL_HEADER_H,
    width: gridW,
    height: gridH,
  }, CELL_GAP);

  function onKeyDown(event: React.KeyboardEvent<SVGSVGElement>) {
    if (!hover) {
      if (['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        setHover({ row: 0, col: 0 });
        event.preventDefault();
      }
      return;
    }
    switch (event.key) {
      case 'ArrowRight': setHover({ row: hover.row, col: Math.min(models.length - 1, hover.col + 1) }); break;
      case 'ArrowLeft': setHover({ row: hover.row, col: Math.max(0, hover.col - 1) }); break;
      case 'ArrowDown': setHover({ row: Math.min(tasks.length - 1, hover.row + 1), col: hover.col }); break;
      case 'ArrowUp': setHover({ row: Math.max(0, hover.row - 1), col: hover.col }); break;
      case 'Home': setHover({ row: 0, col: 0 }); break;
      case 'End': setHover({ row: tasks.length - 1, col: models.length - 1 }); break;
      case 'Escape': setHover(null); return;
      default: return;
    }
    event.preventDefault();
  }

  const hoveredTask = hover ? tasks[hover.row] : null;
  const hoveredModel = hover ? models[hover.col] : null;
  const hoveredScore = hoveredTask && hoveredModel
    ? scores.get(taskKey(hoveredTask.task, hoveredModel.model_ref))?.score ?? null
    : null;

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="font-heading text-sm font-semibold">Task heatmap</h3>
        {saturatedTasks.length > 0 && (
          <button
            type="button"
            onClick={() => setShowSaturated(!showSaturated)}
            className="cursor-pointer text-xs text-muted-foreground hover:text-foreground"
          >
            {showSaturated ? 'Hide' : 'Show'} saturated ({saturatedTasks.length})
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${totalW} ${totalH}`}
          className="w-full touch-none rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          style={{ minHeight: Math.min(totalH, 400), maxHeight: 600 }}
          role="img"
          aria-label={`Task score heatmap. ${tasks.length} tasks, ${models.length} models. Focus and use arrow keys to navigate.`}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onBlur={() => setHover(null)}
        >
          {models.map((m, ci) => (
            <text
              key={m.model_ref}
              x={LABEL_W + ci * (cellW + CELL_GAP) + cellW / 2}
              y={MODEL_HEADER_H - 8}
              textAnchor="middle"
              className="fill-muted-foreground text-[9px]"
            >
              {shortModelLabel(m.model_ref)}
            </text>
          ))}

          {tasks.map((t, ri) => (
            <text
              key={t.task}
              x={LABEL_W - 6}
              y={MODEL_HEADER_H + ri * (CELL_H + CELL_GAP) + CELL_H / 2}
              textAnchor="end"
              dominantBaseline="middle"
              className={cn(
                'text-[9px]',
                hover?.row === ri ? 'fill-foreground font-medium' : 'fill-muted-foreground',
              )}
            >
              {t.task.length > 18 ? t.task.slice(0, 16) + '…' : t.task}
            </text>
          ))}

          {cells.map((cell) => {
            const task = tasks[cell.row];
            const model = models[cell.col];
            const entry = scores.get(taskKey(task.task, model.model_ref));
            const score = entry?.score ?? null;
            const isHovered = hover?.row === cell.row && hover?.col === cell.col;
            const inRow = hover?.row === cell.row;
            const inCol = hover?.col === cell.col;

            return (
              <rect
                key={`${cell.row}-${cell.col}`}
                x={cell.x}
                y={cell.y}
                width={cell.width}
                height={cell.height}
                rx={2}
                className={cn(
                  'transition-opacity',
                  isHovered && 'stroke-foreground',
                )}
                strokeWidth={isHovered ? 1.5 : 0}
                fill="currentColor"
                style={{
                  color: 'var(--chart-1)',
                  opacity: score === null ? 0.05 : (hover && !inRow && !inCol ? 0.4 : 1) * (0.1 + score * 0.9),
                }}
                onPointerEnter={() => setHover({ row: cell.row, col: cell.col })}
                onPointerLeave={() => setHover(null)}
              />
            );
          })}

          {tasks.map((t, ri) => {
            const verdict = report.verdicts[t.task] as TaskVerdict | undefined;
            if (!verdict) return null;
            return (
              <circle
                key={`v-${t.task}`}
                cx={LABEL_W + gridW + CELL_GAP + VERDICT_W / 2}
                cy={MODEL_HEADER_H + ri * (CELL_H + CELL_GAP) + CELL_H / 2}
                r={4}
                className={VERDICT_DOT[verdict]}
              >
                <title>{VERDICT_LABELS[verdict]}</title>
              </circle>
            );
          })}
        </svg>
      </div>

      <p aria-live="polite" className="sr-only">
        {hoveredTask && hoveredModel
          ? `${hoveredTask.task}, ${hoveredModel.model_ref}: ${formatScore(hoveredScore)}`
          : ''}
      </p>

      {hover !== null && hoveredTask && hoveredModel && (
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">{hoveredTask.task}</span>
          {' × '}
          <span className="font-mono">{shortModelLabel(hoveredModel.model_ref)}</span>
          {': '}
          <span className="font-medium text-foreground tabular-nums">{formatScore(hoveredScore)}</span>
        </p>
      )}
    </section>
  );
}
