import 'package:flutter/material.dart';

import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';

/// Horizontal lifecycle stepper: Publicado → Buscando → Chat → Verifica →
/// Ejecuta. Stages at or before [current] are active; the current one pulses.
class ProgressStepper extends StatelessWidget {
  const ProgressStepper({required this.current, super.key});

  final TaskStage current;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    const stages = TaskStage.values;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < stages.length; i++) ...[
          _Node(
            stage: stages[i],
            isDone: i < current.index,
            isCurrent: i == current.index,
            accent: tokens.accentPurple,
            done: tokens.accentCyan,
            idle: tokens.borderSubtle,
            muted: tokens.textMuted,
          ),
          if (i < stages.length - 1)
            Expanded(
              child: Container(
                height: 2,
                margin: const EdgeInsets.only(top: 15),
                color: i < current.index ? tokens.accentCyan : tokens.borderSubtle,
              ),
            ),
        ],
      ],
    );
  }
}

class _Node extends StatelessWidget {
  const _Node({
    required this.stage,
    required this.isDone,
    required this.isCurrent,
    required this.accent,
    required this.done,
    required this.idle,
    required this.muted,
  });

  final TaskStage stage;
  final bool isDone;
  final bool isCurrent;
  final Color accent;
  final Color done;
  final Color idle;
  final Color muted;

  @override
  Widget build(BuildContext context) {
    final active = isDone || isCurrent;
    final circleColor = isCurrent
        ? accent
        : isDone
            ? done
            : Colors.transparent;
    final borderColor = active ? circleColor : idle;

    return SizedBox(
      width: 52,
      child: Column(
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: circleColor,
              shape: BoxShape.circle,
              border: Border.all(color: borderColor, width: 2),
            ),
            child: Icon(
              isDone ? Icons.check : Icons.circle,
              size: isDone ? 16 : 8,
              color: active ? Colors.white : muted,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            stage.label,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: active ? Theme.of(context).colorScheme.onSurface : muted,
                  fontWeight: isCurrent ? FontWeight.w600 : FontWeight.normal,
                ),
          ),
        ],
      ),
    );
  }
}
