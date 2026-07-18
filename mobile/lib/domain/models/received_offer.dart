import 'package:agenttrust_mobile/domain/models/offer.dart';

/// A competing [Offer] paired with the provider identity the requester needs
/// to display and select it. Provider identity rides the A2A message envelope
/// in the real protocol, not the offer body — this app-level pairing carries
/// it for the "Ofertas recibidas" UI.
class ReceivedOffer {
  const ReceivedOffer({
    required this.providerPrincipalId,
    required this.providerName,
    required this.offer,
  });

  final String providerPrincipalId;
  final String providerName;
  final Offer offer;

  double get price => offer.price;
  String get currency => offer.currency;
}
