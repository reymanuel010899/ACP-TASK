import 'package:agenttrust_mobile/domain/models/principal.dart';

/// The signed-in operator's profile and headline reputation stats, shown on
/// Home and Profile.
class UserProfile {
  const UserProfile({
    required this.principal,
    required this.verifiedCount,
    required this.activeCount,
    required this.verificationRate,
    required this.capabilities,
  });

  final Principal principal;

  /// Total tasks verified across all capabilities (Home stat "Verificadas").
  final int verifiedCount;

  /// Tasks currently in flight (Home stat "En curso").
  final int activeCount;

  /// Overall verification rate 0..1 (Home stat "Tasa").
  final double verificationRate;

  /// Capability ids this operator's agents advertise.
  final List<String> capabilities;

  String get displayName => principal.displayName ?? principal.principalId;
}
