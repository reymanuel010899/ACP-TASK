import 'package:flutter/material.dart';

import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_typography.dart';

/// A small pill badge (capability tags, status chips like "T-beta", "EN VIVO").
class AppBadge extends StatelessWidget {
  const AppBadge({
    required this.label,
    required this.color,
    this.icon,
    this.mono = false,
    super.key,
  });

  final String label;
  final Color color;
  final IconData? icon;
  final bool mono;

  @override
  Widget build(BuildContext context) {
    final textStyle = mono
        ? AppTypography.mono(fontSize: 11, color: color)
        : Theme.of(context)
            .textTheme
            .labelSmall
            ?.copyWith(color: color, fontWeight: FontWeight.w600);

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        // ignore: deprecated_member_use
        color: color.withOpacity(0.14),
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 12, color: color),
            const SizedBox(width: AppSpacing.xs),
          ],
          Text(label, style: textStyle),
        ],
      ),
    );
  }
}
