"""Tests for the EcoNet water heater platform."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pyeconet.equipment import EquipmentType
from pyeconet.equipment.water_heater import WaterHeater
from pyeconet.errors import InvalidResponseFormat
import pytest

from homeassistant.components.econet.const import DOMAIN
from homeassistant.components.water_heater import (
    ATTR_AWAY_MODE,
    DOMAIN as WATER_HEATER_DOMAIN,
    SERVICE_SET_AWAY_MODE,
)
from homeassistant.const import ATTR_ENTITY_ID, CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

ENTITY_ID = "water_heater.water_heater"
DEVICE_ID = "1234567890"
SERIAL_NUMBER = "00-00-00-00-00-00-00-00-00"

BASE_EQUIPMENT = {
    "device_name": DEVICE_ID,
    "serial_number": SERIAL_NUMBER,
    "@NAME": {"value": "Water Heater"},
    "@CONNECTED": True,
    "@SETPOINT": {
        "value": 125,
        "constraints": {"lowerLimit": 110, "upperLimit": 140},
    },
    "@AWAY": False,
    "@AWAYCONFIG": True,
}

# Mode list as reported by a heatpumpWaterHeaterGen5.
HEAT_PUMP_EQUIPMENT = BASE_EQUIPMENT | {
    "@TYPE": "heatpumpWaterHeaterGen5",
    "@ENABLED": {"value": 1, "constraints": {"enumText": ["Disabled", "Enabled "]}},
    "@MODE": {
        "value": 1,
        "status": "Energy Saver  ",
        "constraints": {
            "enumText": [
                "Off           ",
                "Energy Saver  ",
                "Heat Pump     ",
                "High Demand   ",
                "Electric/Gas  ",
                "Vacation      ",
            ]
        },
    },
    "@SCHEDULESTATUS": "",
}

# A unit with no Vacation mode and no schedule falls back to @AWAY.
NO_VACATION_EQUIPMENT = BASE_EQUIPMENT | {
    "@TYPE": "electricWaterHeater",
    "@MODE": {
        "value": 1,
        "status": "Energy Saver  ",
        "constraints": {
            "enumText": ["Off           ", "Energy Saver  ", "High Demand   "]
        },
    },
}


async def setup_water_heater(
    hass: HomeAssistant, equipment_info: dict[str, Any]
) -> MagicMock:
    """Set up the water heater platform and return the mocked API."""
    api = MagicMock()
    # Usage reports are polled on every update; this unit reports none.
    api.get_dynamic_action = AsyncMock(side_effect=InvalidResponseFormat)
    water_heater = WaterHeater(dict(equipment_info), api)
    api.get_equipment_by_type = AsyncMock(
        return_value={
            EquipmentType.WATER_HEATER: [water_heater],
            EquipmentType.THERMOSTAT: [],
        }
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_EMAIL: "admin@localhost.com", CONF_PASSWORD: "password0"},
    )
    entry.add_to_hass(hass)

    with (
        patch("pyeconet.EcoNetApiInterface.login", return_value=api),
        patch("homeassistant.components.econet.PLATFORMS", [Platform.WATER_HEATER]),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return api


@pytest.mark.parametrize(
    ("equipment_info", "away_mode", "payload"),
    [
        pytest.param(
            HEAT_PUMP_EQUIPMENT,
            True,
            {"@ENABLED": 1, "@MODE": 5},
            id="vacation_mode_on",
        ),
        pytest.param(
            HEAT_PUMP_EQUIPMENT,
            False,
            {"@SCHEDULERESUME": "resume"},
            id="vacation_mode_off",
        ),
        pytest.param(
            NO_VACATION_EQUIPMENT,
            True,
            {"@AWAY": True},
            id="away_flag_on",
        ),
        pytest.param(
            NO_VACATION_EQUIPMENT,
            False,
            {"@AWAY": False},
            id="away_flag_off",
        ),
    ],
)
async def test_set_away_mode(
    hass: HomeAssistant,
    equipment_info: dict[str, Any],
    away_mode: bool,
    payload: dict[str, Any],
) -> None:
    """Test away mode publishes what the unit needs to start or end an Away Event."""
    api = await setup_water_heater(hass, equipment_info)

    await hass.services.async_call(
        WATER_HEATER_DOMAIN,
        SERVICE_SET_AWAY_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_AWAY_MODE: away_mode},
        blocking=True,
    )

    api.publish.assert_called_once_with(payload, DEVICE_ID, SERIAL_NUMBER)
