"""Pricing configuration for the Provider Agent (unit U2).

Two numbers, with very different visibility:

- ``list_price`` — the public asking price the provider quotes in its
  ``task.offer``. It crosses the wire.
- ``min_price`` — the provider's PRIVATE reservation: the lowest price it will
  accept. It is never serialized (not in the Agent Card, not in an offer, not
  in a counter response). Publishing it would let any requester extract the
  floor by low-balling (R2 / KTD-N2).

The reservation is enforced only in :meth:`ProviderAgent.consider_counter`
logic; nothing serializes it.
"""

DEFAULT_CURRENCY = "USD"
DEFAULT_LIST_PRICE = 5.0
DEFAULT_MIN_PRICE = 3.0


class PricingConfig(object):
    """A provider's public asking price and its private reservation floor."""

    def __init__(
        self,
        list_price=DEFAULT_LIST_PRICE,
        min_price=DEFAULT_MIN_PRICE,
        currency=DEFAULT_CURRENCY,
    ):
        # type: (float, float, str) -> None
        if min_price < 0:
            raise ValueError("min_price must be >= 0")
        if list_price < min_price:
            raise ValueError(
                "list_price (%s) must be >= min_price (%s)"
                % (list_price, min_price)
            )
        self.list_price = float(list_price)
        self.min_price = float(min_price)  # private reservation, never serialized
        self.currency = currency
