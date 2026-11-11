"""Authenticated LAN heartbeat. Carries readiness, never keys or memory addresses."""
import copy
import hmac
import http.client
import ipaddress
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

PHASES={'idle','combat','maintenance','ready','entering','stopped'}


def validate_config(config,own):
    if not isinstance(config,dict):raise ValueError('组队配置格式错误')
    mode=config.get('mode','solo')
    if mode=='solo':return
    if mode not in ('leader','follower'):raise ValueError('组队模式无效')
    peer=config.get('partner','').strip()
    if not peer or peer==own or len(peer)>24:raise ValueError('请填写另一台电脑的完整角色名')
    token=config.get('token','')
    if len(token)!=32 or any(c not in '0123456789abcdef' for c in token):raise ValueError('两台电脑须填写同一组32位配对码')
    port=config.get('port',18770)
    if type(port) is not int or not 1024<=port<=65535:raise ValueError('端口无效')
    if mode=='follower':
        try:address=ipaddress.ip_address(config.get('host',''))
        except ValueError:raise ValueError('请填写大号电脑的局域网 IPv4 地址') from None
        if address.version!=4 or not(address.is_private or address.is_loopback) or address.is_unspecified or address.is_multicast:
            raise ValueError('仅支持局域网 IPv4 地址')


class TeamLink:
    def __init__(self,config,own,*,bind_host='0.0.0.0'):
        validate_config(config,own)
        self.config=dict(config);self.role=config['mode'];self.own=own
        self.lock=threading.Lock();self.closed=threading.Event();self.server=None
        self.peer=None;self.seen=0;self.error=''
        self.state={'v':1,'role':self.role,'name':own,'partner':config['partner'],
                    'session':secrets.token_hex(12) if self.role=='leader' else '',
                    'round':0,'phase':'idle','active':False,'ready_for':None}
        if self.role=='leader':
            link=self
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):
                    self.connection.settimeout(2)
                    if self.path!='/state' or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+link.config['token']):
                        self.send_error(403);return
                    try:
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=2048:raise ValueError()
                        value=json.loads(self.rfile.read(length))
                        if not link.accept(value):raise ValueError()
                        raw=json.dumps(link.snapshot()).encode()
                        self.send_response(200);self.send_header('Content-Type','application/json')
                        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                    except (ValueError,TypeError,KeyError):self.send_error(400)
            self.server=ThreadingHTTPServer((bind_host,config.get('port',18770)),Handler)
            self.server.daemon_threads=True
            self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        else:self.thread=threading.Thread(target=self._poll,daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.state)

    def update(self,**fields):
        with self.lock:self.state.update(fields)

    def accept(self,value):
        expected='follower' if self.role=='leader' else 'leader'
        if not isinstance(value,dict) or value.get('v')!=1 or value.get('role')!=expected:return False
        if value.get('name')!=self.config['partner'] or value.get('partner')!=self.own:return False
        if value.get('phase') not in PHASES or type(value.get('round')) is not int or type(value.get('active')) is not bool:return False
        if not isinstance(value.get('session'),str) or len(value['session'])>48:return False
        ready=value.get('ready_for')
        if ready is not None and not (isinstance(ready,list) and len(ready)==2 and isinstance(ready[0],str) and type(ready[1]) is int):return False
        with self.lock:self.peer=value;self.seen=time.monotonic();self.error=''
        return True

    def remote(self):
        with self.lock:
            return copy.deepcopy(self.peer) if time.monotonic()-self.seen<3 else None

    def ready(self):
        peer=self.remote();own=self.snapshot()
        return bool(peer and peer['active'] and peer['phase']=='ready' and peer.get('ready_for')==[own['session'],own['round']])

    def _poll(self):
        while not self.closed.is_set():
            connection=http.client.HTTPConnection(self.config['host'],self.config.get('port',18770),timeout=1)
            try:
                raw=json.dumps(self.snapshot()).encode()
                connection.request('POST','/state',raw,{'Content-Type':'application/json','Authorization':'Bearer '+self.config['token']})
                response=connection.getresponse();body=response.read(2049)
                if response.status!=200 or len(body)>2048 or not self.accept(json.loads(body)):raise ValueError('角色或配对码不匹配')
            except (OSError,ValueError,http.client.HTTPException) as exc:self.error=str(exc)
            finally:connection.close()
            self.closed.wait(.25)

    def close(self):
        self.update(phase='stopped',active=False)
        self.closed.set()
        if self.server:self.server.shutdown();self.server.server_close()
        self.thread.join(timeout=2)
