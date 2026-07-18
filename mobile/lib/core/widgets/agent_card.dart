import 'package:flutter/material.dart';

import 'package:agenttrust_mobile/core/format.dart';
import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/theme/app_typography.dart';
import 'package:agenttrust_mobile/core/widgets/app_badge.dart';
import 'package:agenttrust_mobile/domain/models/agent_summary.dart';

/// The reusable Agent Card from the design: avatar + name + capability tag,
/// public price (mono), verification rate + task count, and a reputation bar.
class AgentCard extends StatelessWidget {
  const AgentCard({
    required this.agent,
    this.width,
    this.onTap,
    super.key,
  });

  final AgentSummary agent;
  final double? width;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final rate = agent.verificationRate;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.md),
      child: Container(
        width: width,
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: tokens.card,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: tokens.borderSubtle),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Avatar(name: agent.displayName),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        agent.displayName,
                        style: Theme.of(context)
                            .textTheme
                            .titleSmall
                            ?.copyWith(fontWeight: FontWeight.w600),
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      AppBadge(
                        label: agent.capabilityId,
                        color: tokens.accentPurple,
                        mono: true,
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      Fmt.price(agent.listPrice, symbol: true),
                      style: AppTypography.mono(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      '${agent.currency}/task',
                      style: AppTypography.mono(
                        fontSize: 9,
                        color: tokens.textMuted,
                      ),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _IconStat(
                  icon: Icons.verified_user_outlined,
                  label: Fmt.rate(rate),
                  color: tokens.accentGreen,
                ),
                _IconStat(
                  icon: Icons.layers_outlined,
                  label: '${agent.tasksDone} tasks',
                  color: tokens.textMuted,
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            _RepBar(rate: rate, color: tokens.accentGreen),
          ],
        ),
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.name});
  final String name;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final initial = name.isNotEmpty ? name.characters.first.toUpperCase() : '?';
    return Container(
      width: 36,
      height: 36,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        // ignore: deprecated_member_use
        color: tokens.accentPurple.withOpacity(0.14),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Text(
        initial,
        style: Theme.of(context)
            .textTheme
            .titleSmall
            ?.copyWith(color: tokens.accentPurple, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _IconStat extends StatelessWidget {
  const _IconStat({
    required this.icon,
    required this.label,
    required this.color,
  });

  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 13, color: color),
        const SizedBox(width: AppSpacing.xs),
        Text(label, style: AppTypography.mono(fontSize: 12, color: color)),
      ],
    );
  }
}

class _RepBar extends StatelessWidget {
  const _RepBar({required this.rate, required this.color});
  final double? rate;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return ClipRRect(
      borderRadius: BorderRadius.circular(2),
      child: LinearProgressIndicator(
        value: rate ?? 0,
        minHeight: 4,
        backgroundColor: tokens.borderSubtle,
        valueColor: AlwaysStoppedAnimation<Color>(color),
      ),
    );
  }
}
