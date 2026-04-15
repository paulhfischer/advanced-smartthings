from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsSelectEntityDescription,
    denormalize_oven_mode,
    normalize_oven_mode,
    oven_mode_display_language,
)
from .entity import AdvancedSmartThingsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        AdvancedSmartThingsSelectEntity(runtime.coordinator, device, description)
        for device in runtime.devices.values()
        for description in device.supported_entities
        if isinstance(description, AdvancedSmartThingsSelectEntityDescription)
    )


class AdvancedSmartThingsSelectEntity(AdvancedSmartThingsEntity, SelectEntity):
    """SmartThings select entity."""

    entity_description: AdvancedSmartThingsSelectEntityDescription

    @property
    def current_option(self) -> str | None:
        raw_value = self._lookup_path(self.entity_description.value_path)
        if not isinstance(raw_value, str):
            return None
        if self.entity_description.translation_key == "oven_mode":
            return normalize_oven_mode(raw_value, self._oven_mode_language())
        return raw_value

    @property
    def options(self) -> list[str]:
        if self.entity_description.translation_key == "oven_mode":
            options = self._raw_oven_options()
            mapped_options: list[str] = []
            language = self._oven_mode_language()
            for option in options:
                display = normalize_oven_mode(option, language)
                if display is not None and display not in mapped_options:
                    mapped_options.append(display)
            return mapped_options
        raw_options = self._lookup_path(self.entity_description.options_path)
        options = (
            [value for value in raw_options if isinstance(value, str)]
            if isinstance(raw_options, list)
            else []
        )
        current_raw = self._lookup_path(self.entity_description.value_path)
        if isinstance(current_raw, str) and current_raw not in options:
            options.append(current_raw)
        if not options:
            options = list(self.entity_description.fallback_options)
        return options

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported option {option!r} for {self.entity_id}")
        self._require_remote_control_enabled()
        if self.entity_description.translation_key == "oven_mode":
            target = self._resolve_oven_mode_target(option)
            if target is None:
                raise ValueError(f"Unsupported oven mode {option!r} for {self.entity_id}")
            component_id, capability, raw_option = target
            optimistic_updates = [
                (
                    self.entity_description.component_id,
                    self.entity_description.capability,
                    self.entity_description.value_path,
                    raw_option,
                )
            ]
            if (
                component_id != self.entity_description.component_id
                or capability != self.entity_description.capability
            ):
                optimistic_updates.append(
                    (
                        component_id,
                        capability,
                        self.entity_description.value_path,
                        raw_option,
                    )
                )
            await self._async_send_command(
                self.entity_description.command,
                [raw_option],
                component_id=component_id,
                capability=capability,
                optimistic_updates=optimistic_updates,
            )
            return

        await self._async_send_command(
            self.entity_description.command,
            [option],
            optimistic_updates=[
                (
                    self.entity_description.component_id,
                    self.entity_description.capability,
                    self.entity_description.value_path,
                    option,
                )
            ],
        )

    def _raw_oven_options(self) -> list[str]:
        options: list[str] = []
        for component_id, capability in self._oven_mode_sources():
            raw_options = self._lookup_path(
                self.entity_description.options_path,
                component_id=component_id,
                capability=capability,
            )
            if isinstance(raw_options, list):
                for value in raw_options:
                    if isinstance(value, str) and value not in options:
                        options.append(value)

            current_raw = self._lookup_path(
                self.entity_description.value_path,
                component_id=component_id,
                capability=capability,
            )
            if isinstance(current_raw, str) and current_raw not in options:
                options.append(current_raw)

        if not options:
            options = list(self.entity_description.fallback_options)
        return options

    def _resolve_oven_mode_target(self, option: str) -> tuple[str, str, str] | None:
        language = self._oven_mode_language()
        for component_id, capability in self._oven_mode_sources():
            raw_options = self._lookup_path(
                self.entity_description.options_path,
                component_id=component_id,
                capability=capability,
            )
            options = (
                [value for value in raw_options if isinstance(value, str)]
                if isinstance(raw_options, list)
                else []
            )
            current_raw = self._lookup_path(
                self.entity_description.value_path,
                component_id=component_id,
                capability=capability,
            )
            if isinstance(current_raw, str) and current_raw not in options:
                options.append(current_raw)
            if not options:
                continue

            raw_option = denormalize_oven_mode(
                option,
                language=language,
                raw_options=options,
            )
            if raw_option in options:
                return component_id, capability, raw_option
        return None

    def _oven_mode_sources(self) -> list[tuple[str, str]]:
        sources = [
            (self.entity_description.component_id, self.entity_description.capability),
            ("main", "samsungce.ovenMode"),
            (self.entity_description.component_id, "ovenMode"),
            ("main", "ovenMode"),
        ]
        unique_sources: list[tuple[str, str]] = []
        for source in sources:
            if source not in unique_sources:
                unique_sources.append(source)
        return unique_sources

    def _oven_mode_language(self) -> str:
        return oven_mode_display_language(self.hass.config.language)
