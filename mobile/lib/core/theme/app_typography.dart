import 'package:flutter/material.dart';
// import 'package:google_fonts/google_fonts.dart'; // Disabled for compilation

import 'package:agenttrust_mobile/core/theme/app_colors.dart';

/// Typography: using Material Design default fonts (Roboto)
abstract final class AppTypography {
  /// Monospace family helper — use for prices, reputation rates, ids, timers.
  static TextStyle mono({
    double fontSize = 13,
    FontWeight fontWeight = FontWeight.w500,
    Color? color,
    double? letterSpacing,
  }) {
    return TextStyle(
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color ?? AppColors.textPrimary,
      letterSpacing: letterSpacing,
      fontFamily: 'monospace',
    );
  }

  static TextTheme textTheme() {
    final base = ThemeData(brightness: Brightness.dark).textTheme;
    return base.apply(
      bodyColor: AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    );
  }
}
