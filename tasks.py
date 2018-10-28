from io import BytesIO
from celery import Celery
from celery.utils.log import get_task_logger

import redis
import json
import settings
import pycurl
import util
import aiohttp
import asyncio


# TODO (besides test obvi)
# - receive logic

logger = get_task_logger(__name__)

r = redis.StrictRedis()
app = Celery('grahamTangram', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')
app.conf.CELERY_MAX_CACHED_RESULTS = -1

async def communicate_wallet_async(wallet_command,action):
	headers = {"accept": "application/json",
			   "Authorization": settings.node_pass,
			   "Content-Type": "application/json"}
	async with aiohttp.ClientSession() as session:
		async with session.post("http://{0}:{1}/{2}".format(settings.node_ip, settings.node_port,action),json=wallet_command,headers=headers, timeout=300) as resp:
			return await resp.read()

@app.task(bind=True, max_retries=10)
def send_transaction(self, tx):
	"""creates a block and broadcasts it to the network, returns
	a dict if successful. Synchronization is 'loosely' enforced.
	There's not much point in running this function in parallel anyway,
	since the node processes them synchronously. The lock is just
	here to prevent a deadlock condition that has occured on the node"""
	with redis.Redis().lock(tx['source_address'], timeout=300):
		try:
			source_address = tx['source_address']
			to_address = tx['to_address']
			amount = tx['amount']
			uid = tx['uid']
			raw_withdraw_amt = int(amount)

			wallet_command = {
				'identifier': settings.wallet,
				'password': settings.node_pass,
				'account': source_address,
				'change': source_address,
				'link': to_address,
				'amount': amount
			}
			logger.debug("RPC Send")
			action = "actor/wallet/transfer/funds"
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)
			outputText = loop.run_until_complete(communicate_wallet_async(wallet_command,action))
			wallet_output = json.loads(outputText)
			logger.debug("RPC Response")
			txid = None
			#pulowi validacion por error 409
			if source_address == to_address:
				ret = json.dumps({"success": {"source":source_address, "txid":txid, "uid":uid, "destination":to_address, "amount":amount}})
				r.rpush('/tx_completed', ret)
				return ret
			#pulowi block se cambio por work por el momento
			if 'work' in wallet_output:
				txid = wallet_output['work']
				# Also pocket these timely
				logger.info("Pocketing tip for %s, block %s", to_address, txid)
			#pocket_tx(to_address, txid)
			elif 'error' in wallet_output:
				txid = 'invalid'
			if txid is not None:
				ret = json.dumps({"success": {"source":source_address, "txid":txid, "uid":uid, "destination":to_address, "amount":amount}})
				r.rpush('/tx_completed', ret)
				return ret
			else:
				self.retry(countdown=2**self.request.retries)
				return {"status":"retrying"}
		except pycurl.error:
			self.retry(countdown=2**self.request.retries)
			return {"status":"retrying"}
		except Exception as e:
			logger.exception(e)
			logger.debug(wallet_output)
			self.retry(countdown=2**self.request.retries)
			return {"status":"retrying"}

if __name__ == '__main__':
	app.start()
