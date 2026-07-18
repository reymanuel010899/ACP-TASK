/// A provider's public offer to perform a task at a stated price.
/// Mirrors `schemas/offer.schema.json`.
///
/// IMPORTANT (RFC-0002): the provider's private reservation/minimum price is
/// NEVER part of this object. Only the public [price] crosses the wire.
class Offer {
  const Offer({
    required this.taskId,
    required this.capabilityId,
    required this.price,
    required this.currency,
    this.delivery,
  });

  static const String type = 'task.offer';

  final String taskId;
  final String capabilityId;
  final double price;
  final String currency;
  final String? delivery;

  factory Offer.fromJson(Map<String, dynamic> json) => Offer(
        taskId: json['task_id'] as String,
        capabilityId: json['capability_id'] as String,
        price: (json['price'] as num).toDouble(),
        currency: json['currency'] as String,
        delivery: json['delivery'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'type': type,
        'task_id': taskId,
        'capability_id': capabilityId,
        'price': price,
        'currency': currency,
        if (delivery != null) 'delivery': delivery,
      };
}

/// A requester's single-round counter-offer proposing a lower price.
/// Mirrors `schemas/counter-offer.schema.json`.
class CounterOffer {
  const CounterOffer({
    required this.taskId,
    required this.proposedPrice,
    this.currency,
  });

  static const String type = 'task.counter';

  final String taskId;
  final double proposedPrice;
  final String? currency;

  Map<String, dynamic> toJson() => {
        'type': type,
        'task_id': taskId,
        'proposed_price': proposedPrice,
        if (currency != null) 'currency': currency,
      };
}
