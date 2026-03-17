from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.integrations.feishu.cards import (
    build_action_card,
    build_funding_board_card,
    build_orders_card,
    build_positions_card,
    build_strategies_card,
    build_workflows_card,
)
from arb.integrations.feishu.client import FeishuClient
from arb.integrations.feishu.events import FeishuEventHandler, sign_callback

class TestFeishuClient:

    def test_token_refresh_and_message_send(self) -> None:
        calls: list[dict[str, object]] = []

        def transport(request):
            calls.append(request)
            if request['url'].endswith('/tenant_access_token/internal'):
                return {'tenant_access_token': 'token-1', 'expire': 7200}
            return {'data': {'message_id': 'om_xxx'}}
        client = FeishuClient('app', 'secret', transport)
        token = client.get_tenant_access_token(now=0)
        response = client.send_card(receive_id='ou_xxx', card={'hello': 'world'})
        assert token == 'token-1'
        assert response['data']['message_id'] == 'om_xxx'
        assert len(calls) == 2

    def test_request_retries_once(self) -> None:
        state = {'count': 0}

        def transport(request):
            state['count'] += 1
            if state['count'] == 1:
                raise RuntimeError('temporary failure')
            return {'tenant_access_token': 'token-2', 'expire': 7200}
        client = FeishuClient('app', 'secret', transport)
        assert client.refresh_token(now=0) == 'token-2'
        assert state['count'] == 2

class TestFeishuEvents:

    def test_callback_signature_and_challenge(self) -> None:
        handler = FeishuEventHandler(verification_token='verify', signing_secret='secret')
        raw_body = '{"type":"url_verification","challenge":"abc","token":"verify"}'
        headers = {'X-Lark-Request-Timestamp': '1700000000', 'X-Lark-Request-Nonce': 'nonce', 'X-Lark-Signature': sign_callback('secret', '1700000000', 'nonce', raw_body)}
        response = handler.parse_callback(headers, {'type': 'url_verification', 'challenge': 'abc', 'token': 'verify'}, raw_body=raw_body)
        assert response['challenge'] == 'abc'

    def test_card_callback_is_parsed(self) -> None:
        handler = FeishuEventHandler(verification_token='verify')
        payload = {'token': 'verify', 'action': {'value': {'action': 'close', 'target': 'spot_perp:BTC/USDT'}}, 'operator': {'open_id': 'ou_xxx'}}
        response = handler.parse_callback({}, payload, raw_body='{}')
        assert response['type'] == 'card_action'
        assert response['action']['action'] == 'close'
        command = handler.to_command_payload(response)
        assert command['requested_by'] == 'ou_xxx'
        assert command['target'] == 'spot_perp:BTC/USDT'

    def test_dispatch_callback_routes_submit_and_confirm(self) -> None:
        handler = FeishuEventHandler(verification_token='verify')
        calls: list[tuple[str, object]] = []

        class _Api:
            def submit_command(self, token, request):
                calls.append(('submit', (token, request.action, request.target)))
                return {'accepted': True, 'command_id': 'cmd-1', 'status': 'queued'}

            def confirm_command(self, token, command_id, actor):
                calls.append(('confirm', (token, command_id, actor)))
                return {'accepted': True, 'command_id': command_id, 'status': 'queued'}

            def cancel_command(self, token, command_id, actor):
                calls.append(('cancel', (token, command_id, actor)))
                return {'accepted': True, 'command_id': command_id, 'status': 'canceled'}

        submit_callback = {'action': {'action': 'manual_close', 'target': 'funding_spot_perp:binance:BTC/USDT'}, 'operator_id': 'ou_xxx'}
        confirm_callback = {'action': {'action': 'confirm', 'command_id': 'cmd-1'}, 'operator_id': 'ou_xxx'}

        handler.dispatch_callback(submit_callback, control_api=_Api(), token='abc')
        handler.dispatch_callback(confirm_callback, control_api=_Api(), token='abc')

        assert calls[0] == ('submit', ('abc', 'manual_close', 'funding_spot_perp:binance:BTC/USDT'))
        assert calls[1] == ('confirm', ('abc', 'cmd-1', 'ou_xxx'))

class TestFeishuCards:

    def test_cards_render_positions_and_actions(self) -> None:
        positions = build_positions_card([{'exchange': 'binance', 'symbol': 'BTC/USDT', 'direction': 'long', 'quantity': '1'}])
        strategies = build_strategies_card([{'name': 'spot_perp', 'status': 'running'}])
        orders = build_orders_card([{'exchange': 'binance', 'symbol': 'BTC/USDT', 'order_id': 'ord-1', 'status': 'new', 'filled_quantity': '0'}])
        workflows = build_workflows_card([{'workflow_id': 'wf-1', 'exchange': 'binance', 'symbol': 'BTC/USDT', 'status': 'opening'}])
        funding_board = build_funding_board_card([{'exchange': 'binance', 'symbol': 'BTC/USDT', 'net_rate': '0.0008', 'funding_interval_hours': 4, 'annualized_net_rate': '0.876', 'spread_bps': '2', 'liquidity_usd': '1000000'}])
        action = build_action_card('spot_perp:BTC/USDT', 'close', command_id='cmd-1')
        assert 'BTC/USDT' in positions['elements'][0]['content']
        assert 'spot_perp' in strategies['elements'][0]['content']
        assert 'ord-1' in orders['elements'][0]['content']
        assert 'wf-1' in workflows['elements'][0]['content']
        assert 'annualized=0.876' in funding_board['elements'][0]['content']
        assert 'interval=4h' in funding_board['elements'][0]['content']
        assert action['elements'][1]['actions'][0]['value']['action'] == 'close'
        assert action['elements'][1]['actions'][1]['value']['action'] == 'confirm'
