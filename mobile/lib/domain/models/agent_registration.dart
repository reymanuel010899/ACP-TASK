/// Provider-registration input captured on the "Registrar Agente" screen.
///
/// Privacy invariant (mirrors the offer schema): [minPrice] is the provider's
/// private reservation. It is stored locally but must NEVER be displayed back
/// in a read view or included in any offer object that crosses the wire.
class AgentRegistration {
  const AgentRegistration({
    required this.name,
    required this.endpointUrl,
    required this.publicKey,
    required this.capabilities,
    required this.listPrice,
    required this.minPrice,
    required this.currency,
    this.bearerToken,
  });

  final String name;
  final String endpointUrl;
  final String publicKey;
  final List<String> capabilities;
  final double listPrice;
  final double minPrice; // private — never serialized outward
  final String currency;
  final String? bearerToken;
}
