from source_helpers import parse_source
import ast, asyncio, dataclasses, re, secrets, types, logging
from pathlib import Path
from custom_components.ninebot_e_scooters.discovery import is_scooter_advertisement, needs_explicit_model
src = Path(__file__).resolve().parents[1] / 'custom_components' / 'ninebot_e_scooters'
parsed=parse_source((src/'config_flow.py').read_text())
configs=[n for n in parsed.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]

class FakeConfigFlow:
    def __init__(self): self.context={}
    def __init_subclass__(cls, **kwargs): super().__init_subclass__()
    def _async_current_ids(self, include_ignore=False): return set()
    async def async_set_unique_id(self, address): self.uid=address
    def _abort_if_unique_id_configured(self): return None
    def async_show_form(self, **kwargs): return {'type':'form',**kwargs}
    def async_create_entry(self, **kwargs): return {'type':'entry',**kwargs}
    def async_abort(self, **kwargs): return {'type':'abort',**kwargs}

class FakeBT:
    def __init__(self, devices): self.devices=devices;self.scans=0
    def async_discovered_service_info(self,hass,connectable):
        return self.devices if connectable else self.devices
    async def async_request_active_scan(self,hass): self.scans+=1

class Vol:
    @staticmethod
    def Required(k, **kw): return k
    @staticmethod
    def Optional(k, **kw): return k
    @staticmethod
    def In(choices): return choices
    @staticmethod
    def Schema(schema): return schema
    @staticmethod
    def Coerce(kind): return kind
    @staticmethod
    def Range(**kwargs): return kwargs
    @staticmethod
    def All(*args): return args

class FakeStore:
    contents = {}
    def __init__(self, _hass, _version, key, **_kwargs): self.key=key
    async def async_load(self): return self.contents.get(self.key)

fake_bt=FakeBT([])
namespace={'__name__':'fake_flow','__builtins__':__builtins__, 'Any':object,
    'ConfigFlow':FakeConfigFlow,'OptionsFlow':object,'ConfigEntry':object,
    'ConfigFlowResult':object,'DOMAIN':'ninebot_e_scooters','CONF_ADDRESS':'address',
    'NUS_SERVICE_UUID':'6e400001-b5a3-f393-e0a9-e50e24dcca9e',
    'CONF_POLL_INTERVAL':'poll_interval','DEFAULT_POLL_INTERVAL':10,'MAX_POLL_INTERVAL':120,
    'CONF_MODEL':'model','AUTO_MODEL':'Automatisch',
    'LEGACY_XIAOMI_MODELS':('Automatisch','Mi Electric Scooter 1S'),
    'MODEL':'Mi Electric Scooter 1S',
    'MIN_POLL_INTERVAL':5,'bluetooth':fake_bt,'vol':Vol,'secrets':secrets,
    'asyncio':asyncio,'re':re,'_LOGGER':logging.getLogger('test'),
    'callback':lambda func:func,
    'Store': FakeStore, 'storage_key': lambda addr:addr,
    'restore': lambda payload, _address: (types.SimpleNamespace(serial=payload),None) if payload else (None,None),
    'is_scooter_advertisement': is_scooter_advertisement,
    'needs_explicit_model': needs_explicit_model,
    'identify_model': lambda serial, _name: types.SimpleNamespace(model='Mi Electric Scooter 1S' if serial.startswith('25700/') else None)}
mod=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+configs,type_ignores=[])
exec(compile(ast.fix_missing_locations(mod), '<fake_config_flow>', 'exec'),namespace)
Flow=namespace['NinebotScooterConfigFlow']

@dataclasses.dataclass
class Info:
    address:str
    name:str
    service_uuids:list

async def main():
    no=Flow();no.hass=object();no.context={}
    r=await no.async_step_user()
    assert r['step_id']=='retry_scan',r
    assert fake_bt.scans==1
    r=await no.async_step_retry_scan({})
    assert r['step_id']=='retry_scan'
    # With a real HA-discovered MIScooter, the config flow must show it by name
    # without initiating a separate Bluetooth connection.
    fake_bt.devices=[Info('D8:9B:B1:50:DD:25','MIScooter5977',[])]
    got=Flow();got.hass=object();got.context={}
    r=await got.async_step_user()
    assert r['step_id']=='user' and 'MIScooter5977' in list(r['data_schema'].values())[0]['D8:9B:B1:50:DD:25']
    assert 'model' in r['data_schema']
    r=await got.async_step_user({'address':'D8:9B:B1:50:DD:25'})
    assert r['type']=='entry' and r['data']['bluetooth_name']=='MIScooter5977'
    assert r['options']['model']=='Automatisch'
    FakeStore.contents['D8:9B:B1:50:DD:25']='25700/12345678'
    saved=Flow();saved.hass=object();saved.context={}
    r=await saved.async_step_user()
    assert 'MIScooter5977 (Mi Electric Scooter 1S)' in r['data_schema']['address']['D8:9B:B1:50:DD:25']
    another=Flow();another.hass=object();another.context={}
    await another.async_step_user()
    r=await another.async_step_user({'address':'D8:9B:B1:50:DD:25','model':'Mi Electric Scooter 1S'})
    assert r['options']['model']=='Mi Electric Scooter 1S'
    # Manual fallback is optional, not required for the normal path.
    manual=Flow();manual.hass=object();manual.context={}
    r=await manual.async_step_retry_scan({'manual_address':'D8:9B:B1:50:DD:25','manual_name':'MIScooter5977'})
    assert r['type']=='entry'
    r=await manual.async_step_retry_scan({'manual_address':'NOT-MAC','manual_name':'MIScooter5977'})
    assert r['errors']['manual_address']=='invalid_address'

    # Test actual coordinator write method with a simulated Bleak client.
    ct=parse_source((src/'coordinator.py').read_text())
    cls=next(x for x in ct.body if isinstance(x,ast.ClassDef) and x.name=='ScooterCoordinator')
    method=next(x for x in cls.body if isinstance(x,ast.AsyncFunctionDef) and x.name=='_async_write_packet')
    fake_cls=ast.ClassDef(name='WriteTester', bases=[],keywords=[],body=[method],decorator_list=[])
    wm=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0), fake_cls],type_ignores=[])
    class BleakError(Exception):pass
    class ScooterConnectionError(Exception):pass
    class FakeClient:
        def __init__(self):self.is_connected=True;self.parts=[]
        async def write_gatt_char(self,char,data,response):self.parts.append((bytes(data),response))
    wns={'__builtins__':__builtins__,'Any':object,'BleakError':BleakError,
         'ScooterConnectionError':ScooterConnectionError,'asyncio':asyncio,'_LOGGER':logging.getLogger('test')}
    exec(compile(ast.fix_missing_locations(wm),'<fake_write>','exec'),wns)
    tested=wns['WriteTester']();tested._client=FakeClient();tested._tx_char=types.SimpleNamespace(properties=['write','write-without-response'])
    await tested._async_write_packet(bytes(range(43)))
    assert [len(p[0]) for p in tested._client.parts]==[20,20,3]
    assert all(p[1] is False for p in tested._client.parts)
    print('PASS: empty cache -> rescan form; MIScooter name -> selection and entry; manual fallback; invalid MAC; 43-byte encrypted frame -> 20/20/3 writes')
asyncio.run(main())
