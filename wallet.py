from decimal import Decimal
import util
import db
import datetime
import settings
import asyncio
import aiohttp
import socket
import json



wallet = settings.wallet

logger = util.get_logger('wallet')
logger_newuser = util.get_logger('usr', log_file='user_creation.log')

async def communicate_wallet_async_get(wallet_command,action):
	headers = {"accept": "application/json",
			   "Authorization": settings.node_pass,
			   "Content-Type": "application/json"}
	async with aiohttp.ClientSession() as session:
		async with session.get("http://{0}:{1}/{2}".format(settings.node_ip, settings.node_port,action),headers=headers, timeout=300) as resp:
			return await resp.read()

async def communicate_wallet_async(wallet_command,action):
	headers = {"accept": "application/json",
			   "Authorization": settings.node_pass,
			   "Content-Type": "application/json"}
	async with aiohttp.ClientSession() as session:
		async with session.post("http://{0}:{1}/{2}".format(settings.node_ip, settings.node_port,action),json=wallet_command,headers=headers, timeout=300) as resp:
			return await resp.read()

async def get_blocks():
	wallet_command = {}
	action = "explorer/blocks/unsettled/count"
	outputText = await communicate_wallet_async_get(wallet_command,action)
	wallet_output = json.loads(outputText)
	return (wallet_output['length'])

async def create_or_fetch_user(user_id, user_name):
	logger.info('attempting to fetch user %s ...', user_id)
	user = db.get_user_by_id(user_id)
	if user is None:
		logger.info('user %s does not exist. creating new user ...',
					user_id)
		wallet_command = {'identifier': wallet, 'password':  settings.node_pass}
		action = "actor/wallet/address"
		outputText = await communicate_wallet_async(wallet_command,action)
		wallet_output = json.loads(outputText)
		address = wallet_output['address']
		#pulowi claim
		wallet_command = {'identifier': wallet, 'password':  settings.node_pass,'address':  address,'amount':  100}
		action = "actor/wallet/reward"
		outputText = await communicate_wallet_async(wallet_command,action)
		wallet_output = json.loads(outputText)
		reward_block = wallet_output['reward_block']
		logger.info('user Reward complete "reward_block": %s', reward_block)
		#pulowi por el momento no se necesita
		#wallet_command = {'action': 'account_representative_set', 'wallet': wallet, 'account':address, 'representative':settings.representative }
		#await communicate_wallet_async(wallet_command)
		user = db.create_user(user_id=user_id, user_name=user_name,
							  wallet_address=address)
		logger.info('user %s created.', user_id)
		logger_newuser.info('user_id: %s, user_name: %s, wallet_address: %s', user_id, user_name, address)
		return user
	else:
		logger.info('user %s fetched.', user_id)
		return user


async def get_balance(user):
	user_id = user.user_id
	logger.info('getting balance for user %s', user_id)
	if user is None:
		logger.info('user %s does not exist.', user_id)
		return {'actual':0,
			'available':0,
			'pending_send':0,
			'pending':0}
	else:
		logger.info('Fetching balance from wallet for %s', user_id)
		wallet_command = {'identifier': wallet, 'password':  settings.node_pass,'address':  user.wallet_address}
		action = "actor/wallet/balance"
		outputText = await communicate_wallet_async(wallet_command,action)
		wallet_output = json.loads(outputText)
		if 'balance' not in wallet_output:
			# Ops
			return None
		actual_balance = int(Decimal(wallet_output['balance']))
		#pulowi pendinte
		#pending_balance = int(wallet_output['pending'])
		pending_balance = 0
		actual_balance = (actual_balance)
		pending_balance = (pending_balance)
		return {'actual':int(actual_balance),
			'available': int(actual_balance) - user.pending_send,
			'pending_send': user.pending_send,
			'pending':int(pending_balance) + user.pending_receive,
			}

async def make_transaction_to_address(source_user, amount, withdraw_address, uid, target_id=None, giveaway_id=0, verify_address=False):
	# Do not validate address for giveaway tx because we do not know it yet
	if verify_address:
		# Check to see if the withdraw address is valid
		#pulowi falta servicio de validacion
		#wallet_command = {'action': 'validate_account_number',
		#		  'account': withdraw_address}
		#address_validation = await communicate_wallet_async(wallet_command)

		#if ((withdraw_address[:4] == 'ban_' and len(withdraw_address) != 64)
		#		or address_validation['valid'] != '1'):
		#	raise util.TipBotException('invalid_address')

		if ((withdraw_address[:4] == 'tgm_' and len(withdraw_address) != 106)):
			raise util.TipBotException('invalid_address')


	amount = int(amount)
	if amount >= 1:
		# See if destination address belongs to a user
		if target_id is None:
			user = db.get_user_by_wallet_address(withdraw_address)
			if user is not None:
				target_id=user.user_id
		# Update pending send for user
		db.create_transaction(source_user, uid, withdraw_address,amount, target_id, giveaway_id)
		logger.info('TX queued, uid %s', uid)
	else:
		raise util.TipBotException('balance_error')

	return amount

async def make_transaction_to_user(user, amount, target_user_id, target_user_name, uid):
	target_user = await create_or_fetch_user(target_user_id, target_user_name)
	try:
		actual_tip_amount = await make_transaction_to_address(user, amount, target_user.wallet_address, uid, target_user_id)
	except util.TipBotException as e:
		return 0

	logger.info('tip queued. (from: %s, to: %s, amount: %d, uid: %s)',
				user.user_id, target_user.user_id, actual_tip_amount, uid)
	return actual_tip_amount
