"""InMemoryProfileCardStore：实体档案卡内存库（按 visible_to 过滤，幂等 upsert）。

与三 store 同构。upsert 按 entity_name 覆盖，但**保留已存在卡片的 locked 字段**
（P4 编辑保护；P1 无编辑，退化为覆盖）。list/get 按 AccessContext 过滤。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.profile_card import ProfileCard, merge_profile_card
from calliodesmo.stores.visibility import visible_to


class InMemoryProfileCardStore:
    def __init__(self) -> None:
        self._cards: dict[str, ProfileCard] = {}

    async def upsert(self, cards: list[ProfileCard]) -> None:
        for card in cards:
            existing = self._cards.get(card.entity_name)
            self._cards[card.entity_name] = (
                merge_profile_card(existing, card) if existing is not None else card
            )

    async def get(self, entity_name: str, *, access: AccessContext) -> ProfileCard | None:
        card = self._cards.get(entity_name)
        if card is None or not visible_to(card, access):
            return None
        return card

    async def list(self, *, access: AccessContext) -> list[ProfileCard]:
        visible = [c for c in self._cards.values() if visible_to(c, access)]
        visible.sort(key=lambda c: c.entity_name)
        return visible

    def __len__(self) -> int:
        return len(self._cards)
