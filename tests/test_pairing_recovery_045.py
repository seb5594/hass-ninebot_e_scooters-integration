from source_helpers import parse_source
"""Regression checks for 0.4.5: explicit button confirmation and retry-safe key."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

from custom_components.ninebot_e_scooters.ninebot_packet import NinebotPacket
from protocol_scope import add_protocol_symbols

SRC = Path(__file__).resolve().parents[1] / "custom_components/ninebot_e_scooters/coordinator.py"
TREE = parse_source(SRC.read_text())
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ScooterCoordinator")
METHOD = next(n for n in CLASS.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_pair_current_session")
MOD = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), METHOD], type_ignores=[])

class ScooterConnectionError(Exception):
    pass

class Notifications:
    def __init__(self):
        self.created=[]
        self.dismissed=[]
    def async_create(self, hass, msg, title, notification_id):
        self.created.append((msg, title, notification_id))
    def async_dismiss(self, hass, id):
        self.dismissed.append(id)

def setup(timeout=0.03):
    notify=Notifications()
    ns={"asyncio":asyncio,"_LOGGER":logging.getLogger('pairing-test'),
        "ScooterConnectionError":ScooterConnectionError, "persistent_notification":notify,
        "PAIRING_TIMEOUT":timeout,"STORED_KEY_RECOVERY_TIMEOUT":timeout,"PAIRING_REPLY_TIMEOUT":0.85,"PAIRING_RETRY_PAUSE":0.001,"PAIRING_RETRY_INTERVAL":0.002,
        "make_ping":lambda key:NinebotPacket(0x3e,0x21,0x5c,0,bytes(key)),
        "make_pair":lambda serial:NinebotPacket(0x3e,0x21,0x5d,0,serial),
        "CMD_PING":0x5c,"CMD_PAIR":0x5d}
    add_protocol_symbols(ns)
    exec(compile(ast.fix_missing_locations(MOD),str(SRC),"exec"),ns)
    updates=[]
    entry=SimpleNamespace(entry_id="e1",data={"app_key":"ab"*16},)
    hass=SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=lambda e,**kw:updates.append(kw)))
    o=SimpleNamespace(_pairing_serial=b'12345678901234',_app_key=bytes.fromhex('ab'*16),
        _pairing_completed=False,_pairing_failed=False,_raw_notification_count=1,
        _rejected_crypto_frames=0,entry=entry,hass=hass)
    return ns['_async_pair_current_session'],o,notify,updates

def test_timeout_does_not_poison_key_or_permanently_disable_pairing():
    run,o,notify,updates=setup(timeout=.027)
    sends=[]
    async def request(packet,**kwargs):
        sends.append((packet.command,bytes(packet.data),kwargs))
        return None
    o._async_crypto_request=request
    async def test():
        try:
            await run(o)
        except ScooterConnectionError as ex:
            assert '0x5C01' in str(ex)
        else: assert False
    asyncio.run(test())
    assert len(sends)>1
    assert all(p[0]==0x5c and p[1]==o._app_key and p[2]['quiet_timeout'] for p in sends)
    assert o._pairing_failed is False
    assert o._pairing_completed is False
    assert o.entry.data['app_key']=='ab'*16
    assert updates==[]
    assert len(notify.created)==2
    assert notify.dismissed==[]

def test_success_keeps_same_key_and_dismisses_notification():
    run,o,notify,updates=setup()
    sent=[]
    async def request(packet,**kwargs):
        sent.append(packet.command)
        return NinebotPacket(0x21,0x3e,packet.command,1)
    o._async_crypto_request=request
    async def confirm_5d():
        response=await request(NinebotPacket(0x3e,0x21,0x5d,0,b"12345678901234"))
        assert response.index==1
    o._async_confirm_pairing_5d=confirm_5d
    asyncio.run(run(o))
    assert sent==[0x5c,0x5d]
    assert o._pairing_completed is True
    assert updates[0]['data']['paired'] is True
    assert updates[0]['data']['app_key']=='ab'*16
    assert len(notify.dismissed)==1


