import 'package:flutter/material.dart';

import 'package:agenttrust_mobile/core/theme/app_colors.dart';

/// Semantic design tokens that Material's [ColorScheme] does not model:
/// the four accent colors, card/border colors, and input background.
///
/// Attached to [ThemeData] via [ThemeExtension] so widgets read them with
/// `Theme.of(context).extension<AppTokens>()!` and never hard-code hex values.
@immutable
class AppTokens extends ThemeExtension<AppTokens> {
  const AppTokens({
    required this.accentPurple,
    required this.accentGreen,
    required this.accentCyan,
    required this.accentPink,
    required this.card,
    required this.cardHover,
    required this.input,
    required this.borderSubtle,
    required this.borderActive,
    required this.textMuted,
  });

  final Color accentPurple;
  final Color accentGreen;
  final Color accentCyan;
  final Color accentPink;
  final Color card;
  final Color cardHover;
  final Color input;
  final Color borderSubtle;
  final Color borderActive;
  final Color textMuted;

  static const dark = AppTokens(
    accentPurple: AppColors.accentPurple,
    accentGreen: AppColors.accentGreen,
    accentCyan: AppColors.accentCyan,
    accentPink: AppColors.accentPink,
    card: AppColors.bgCard,
    cardHover: AppColors.bgCardHover,
    input: AppColors.bgInput,
    borderSubtle: AppColors.borderSubtle,
    borderActive: AppColors.borderActive,
    textMuted: AppColors.textMuted,
  );

  /// Convenience accessor used throughout the UI.
  static AppTokens of(BuildContext context) =>
      Theme.of(context).extension<AppTokens>()!;

  @override
  AppTokens copyWith({
    Color? accentPurple,
    Color? accentGreen,
    Color? accentCyan,
    Color? accentPink,
    Color? card,
    Color? cardHover,
    Color? input,
    Color? borderSubtle,
    Color? borderActive,
    Color? textMuted,
  }) {
    return AppTokens(
      accentPurple: accentPurple ?? this.accentPurple,
      accentGreen: accentGreen ?? this.accentGreen,
      accentCyan: accentCyan ?? this.accentCyan,
      accentPink: accentPink ?? this.accentPink,
      card: card ?? this.card,
      cardHover: cardHover ?? this.cardHover,
      input: input ?? this.input,
      borderSubtle: borderSubtle ?? this.borderSubtle,
      borderActive: borderActive ?? this.borderActive,
      textMuted: textMuted ?? this.textMuted,
    );
  }

  @override
  AppTokens lerp(ThemeExtension<AppTokens>? other, double t) {
    if (other is! AppTokens) return this;
    return AppTokens(
      accentPurple: Color.lerp(accentPurple, other.accentPurple, t)!,
      accentGreen: Color.lerp(accentGreen, other.accentGreen, t)!,
      accentCyan: Color.lerp(accentCyan, other.accentCyan, t)!,
      accentPink: Color.lerp(accentPink, other.accentPink, t)!,
      card: Color.lerp(card, other.card, t)!,
      cardHover: Color.lerp(cardHover, other.cardHover, t)!,
      input: Color.lerp(input, other.input, t)!,
      borderSubtle: Color.lerp(borderSubtle, other.borderSubtle, t)!,
      borderActive: Color.lerp(borderActive, other.borderActive, t)!,
      textMuted: Color.lerp(textMuted, other.textMuted, t)!,
    );
  }
}
