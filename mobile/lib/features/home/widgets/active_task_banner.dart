import 'package:flutter/material.dart';

import 'package:agenttrust_mobile/core/format.dart';
import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/widgets/app_badge.dart';
import 'package:agenttrust_mobile/core/widgets/progress_stepper.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';

/// The "Tarea en curso" banner shown on Home while a task is being tracked.
class ActiveTaskBanner extends StatelessWidget {
  const ActiveTaskBanner({required this.task, this.onTap, super.key});

  final Task task;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final live = !task.isTerminal;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: tokens.card,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(
            color: live ? tokens.accentPurple : tokens.borderSubtle,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.bolt, size: 16, color: tokens.accentPurple),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  task.isTerminal ? 'Tarea completada' : 'Tarea en curso',
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const Spacer(),
                if (live)
                  AppBadge(
                    label: 'EN VIVO',
                    color: tokens.accentGreen,
                    icon: Icons.circle,
                  )
                else
                  AppBadge(
                    label: 'VERIFICADA',
                    color: tokens.accentGreen,
                    icon: Icons.verified_user,
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              task.description,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Icon(Icons.payments_outlined,
                    size: 14, color: tokens.textMuted),
                const SizedBox(width: AppSpacing.xs),
                Text(
                  'Hasta ${Fmt.price(task.budget, currency: task.currency)}',
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: tokens.textMuted),
                ),
                const Spacer(),
                Text(
                  Fmt.ago(task.createdAt),
                  style: Theme.of(context)
                      .textTheme
                      .labelSmall
                      ?.copyWith(color: tokens.textMuted),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
            ProgressStepper(current: task.stage),
          ],
        ),
      ),
    );
  }
}
