import 'package:flutter/material.dart';

/// Raw design tokens, transcribed verbatim from the Pencil design file
/// (`pencil-new.pen`, AgentTrust mobile). These are the single source of truth
/// for color; higher layers (ColorScheme, [AppTokens]) map them into the theme.
/// UI code should read colors from `Theme.of(context)` rather than referencing
/// these constants directly, except where a semantic slot does not exist.
abstract final class AppColors {
  // Backgrounds
  static const bgPrimary = Color(0xFF0A0A14);
  static const bgCard = Color(0xFF13131F);
  static const bgCardHover = Color(0xFF1A1A2E);
  static const bgInput = Color(0xFF0F0F1A);

  // Text
  static const textPrimary = Color(0xFFF5F5F7);
  static const textSecondary = Color(0xFF8B8B9E);
  static const textMuted = Color(0xFF5A5A6E);

  // Accents
  static const accentPurple = Color(0xFFA855F7);
  static const accentGreen = Color(0xFF10B981);
  static const accentCyan = Color(0xFF06B6D4);
  static const accentPink = Color(0xFFEC4899);

  // Borders
  static const borderSubtle = Color(0xFF1E1E2E);
  static const borderActive = Color(0xFFA855F7);

  // Derived translucent tints used in the design.
  static const purpleTint = Color(0x25A855F7); // ~15% purple (tab pill, avatar)
  static const purpleTintStrong = Color(0x40A855F7);
  static const cardTranslucent = Color(0xCC13131F); // frosted tab bar fill
}
