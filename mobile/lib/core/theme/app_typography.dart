import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:agenttrust_mobile/core/theme/app_colors.dart';

/// Typography built from the Pencil design: Inter for UI/body/headings, and a
/// monospace family for numeric slots (prices, stats, ids).
///
/// The design specifies Geist Mono; `google_fonts` doesn't ship it, so we use
/// JetBrains Mono (the closest geometric mono). Swap here if you bundle the
/// Geist Mono `.ttf`. Fonts load via `google_fonts` (fetched + cached on first
/// run) so no binary assets need bundling.
abstract final class AppTypography {
  /// Monospace family helper — use for prices, reputation rates, ids, timers.
  static TextStyle mono({
    double fontSize = 13,
    FontWeight fontWeight = FontWeight.w500,
    Color? color,
    double? letterSpacing,
  }) {
    return GoogleFonts.jetBrainsMono(
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color ?? AppColors.textPrimary,
      letterSpacing: letterSpacing,
    );
  }

  static TextTheme textTheme() {
    final base = ThemeData(brightness: Brightness.dark).textTheme;
    return GoogleFonts.interTextTheme(base).apply(
      bodyColor: AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    );
  }
}
