/// Small formatting helpers used across screens.
abstract final class Fmt {
  /// A verification rate (0..1) as a percentage string, or "—" when neutral.
  static String rate(double? value) =>
      value == null ? '—' : '${(value * 100).toStringAsFixed(1)}%';

  /// A price with currency, e.g. "$8" or "6.00 USD".
  static String price(double value, {String? currency, bool symbol = false}) {
    final n = value == value.roundToDouble()
        ? value.toStringAsFixed(symbol ? 0 : 2)
        : value.toStringAsFixed(2);
    if (symbol) return '\$$n';
    return currency == null ? n : '$n $currency';
  }

  /// Coarse relative time in Spanish, e.g. "hace 3 min".
  static String ago(DateTime when, {DateTime? now}) {
    final ref = now ?? DateTime(2026, 7, 17, 9, 44);
    final d = ref.difference(when);
    if (d.inMinutes < 1) return 'ahora';
    if (d.inMinutes < 60) return 'hace ${d.inMinutes} min';
    if (d.inHours < 24) return 'hace ${d.inHours} h';
    return 'hace ${d.inDays} d';
  }
}
