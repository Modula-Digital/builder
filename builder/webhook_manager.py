"""
Modula Builder - Webhook Manager with Retry Logic

Implements reliable webhook delivery with:
- Exponential backoff retry
- Dead letter queue
- Webhook signing
- Delivery tracking
"""

import frappe
import requests
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from enum import Enum


class WebhookStatus(Enum):
    """Webhook delivery status"""
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"


class WebhookManager:
    """Manages webhook delivery with retry logic"""

    # Retry configuration
    MAX_RETRIES = 5
    RETRY_DELAYS = [2, 4, 8, 16, 32]  # seconds (exponential backoff)
    TIMEOUT = 30  # seconds
    DEAD_LETTER_AFTER_HOURS = 24

    @staticmethod
    def send_webhook(
        url: str,
        payload: Dict[str, Any],
        event_type: str,
        secret: Optional[str] = None,
        retry: bool = True
    ) -> Dict[str, Any]:
        """
        Send webhook with retry logic

        Args:
            url: Webhook URL
            payload: Payload data
            event_type: Event type (publish, delete, etc.)
            secret: Secret for signing (optional)
            retry: Whether to retry on failure

        Returns:
            Delivery result
        """
        # Create webhook record
        webhook_doc = frappe.get_doc({
            'doctype': 'Builder Webhook Log',
            'url': url,
            'event_type': event_type,
            'payload_json': json.dumps(payload),
            'status': WebhookStatus.PENDING.value,
            'retry_count': 0
        })
        webhook_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Attempt delivery
        result = WebhookManager._deliver_webhook(
            webhook_doc.name,
            url,
            payload,
            event_type,
            secret
        )

        if not result['success'] and retry:
            # Queue for retry
            WebhookManager._queue_retry(webhook_doc.name)

        return result

    @staticmethod
    def _deliver_webhook(
        webhook_id: str,
        url: str,
        payload: Dict[str, Any],
        event_type: str,
        secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Attempt webhook delivery

        Returns:
            Delivery result with success status
        """
        try:
            # Add metadata to payload
            full_payload = {
                **payload,
                'webhook_id': webhook_id,
                'event_type': event_type,
                'timestamp': datetime.now().isoformat()
            }

            # Prepare headers
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'ModulaBuilder/1.0',
                'X-Webhook-Event': event_type
            }

            # Add signature if secret provided
            if secret:
                signature = WebhookManager._sign_payload(full_payload, secret)
                headers['X-Webhook-Signature'] = signature

            # Send request
            start_time = time.time()
            response = requests.post(
                url,
                json=full_payload,
                headers=headers,
                timeout=WebhookManager.TIMEOUT
            )
            response_time = int((time.time() - start_time) * 1000)

            success = response.status_code in [200, 201, 202, 204]

            # Update webhook log
            webhook_doc = frappe.get_doc('Builder Webhook Log', webhook_id)
            webhook_doc.status = WebhookStatus.DELIVERED.value if success else WebhookStatus.FAILED.value
            webhook_doc.response_code = response.status_code
            webhook_doc.response_body = response.text[:1000]  # Limit size
            webhook_doc.response_time_ms = response_time
            webhook_doc.delivered_at = datetime.now() if success else None
            webhook_doc.save(ignore_permissions=True)
            frappe.db.commit()

            return {
                'success': success,
                'status_code': response.status_code,
                'response': response.text,
                'response_time_ms': response_time
            }

        except requests.Timeout:
            WebhookManager._update_webhook_error(webhook_id, 'Timeout', 408)
            return {'success': False, 'error': 'Timeout'}

        except requests.ConnectionError as e:
            WebhookManager._update_webhook_error(webhook_id, f'Connection error: {str(e)}', 0)
            return {'success': False, 'error': 'Connection error'}

        except Exception as e:
            WebhookManager._update_webhook_error(webhook_id, str(e), 0)
            return {'success': False, 'error': str(e)}

    @staticmethod
    def _sign_payload(payload: Dict[str, Any], secret: str) -> str:
        """
        Sign payload with HMAC-SHA256

        Args:
            payload: Payload to sign
            secret: Secret key

        Returns:
            Hex signature
        """
        payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
        signature = hmac.new(
            secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"

    @staticmethod
    def verify_signature(payload: Dict[str, Any], signature: str, secret: str) -> bool:
        """
        Verify webhook signature

        Args:
            payload: Received payload
            signature: Received signature
            secret: Secret key

        Returns:
            True if signature is valid
        """
        expected_signature = WebhookManager._sign_payload(payload, secret)
        return hmac.compare_digest(signature, expected_signature)

    @staticmethod
    def _update_webhook_error(webhook_id: str, error: str, status_code: int):
        """Update webhook log with error"""
        webhook_doc = frappe.get_doc('Builder Webhook Log', webhook_id)
        webhook_doc.status = WebhookStatus.FAILED.value
        webhook_doc.response_code = status_code
        webhook_doc.response_body = error
        webhook_doc.save(ignore_permissions=True)
        frappe.db.commit()

    @staticmethod
    def _queue_retry(webhook_id: str):
        """Queue webhook for retry"""
        webhook_doc = frappe.get_doc('Builder Webhook Log', webhook_id)
        webhook_doc.status = WebhookStatus.RETRYING.value
        webhook_doc.retry_count = webhook_doc.retry_count + 1
        webhook_doc.next_retry_at = datetime.now() + timedelta(
            seconds=WebhookManager.RETRY_DELAYS[
                min(webhook_doc.retry_count - 1, len(WebhookManager.RETRY_DELAYS) - 1)
            ]
        )
        webhook_doc.save(ignore_permissions=True)
        frappe.db.commit()

    @staticmethod
    def process_retries():
        """
        Process pending webhook retries
        Run this via Frappe scheduler every minute
        """
        # Get webhooks due for retry
        webhooks = frappe.get_all(
            'Builder Webhook Log',
            filters={
                'status': WebhookStatus.RETRYING.value,
                'next_retry_at': ['<=', datetime.now()],
                'retry_count': ['<', WebhookManager.MAX_RETRIES]
            },
            fields=['name', 'url', 'payload_json', 'event_type']
        )

        for webhook in webhooks:
            payload = json.loads(webhook.payload_json)

            result = WebhookManager._deliver_webhook(
                webhook.name,
                webhook.url,
                payload,
                webhook.event_type,
                frappe.conf.get('modula_jwt_secret')
            )

            if not result['success']:
                # Check if max retries reached
                webhook_doc = frappe.get_doc('Builder Webhook Log', webhook.name)
                if webhook_doc.retry_count >= WebhookManager.MAX_RETRIES:
                    # Move to dead letter queue
                    webhook_doc.status = WebhookStatus.DEAD_LETTER.value
                    webhook_doc.save(ignore_permissions=True)
                    frappe.db.commit()

                    # Send alert
                    WebhookManager._send_dead_letter_alert(webhook.name)
                else:
                    # Queue for next retry
                    WebhookManager._queue_retry(webhook.name)

    @staticmethod
    def _send_dead_letter_alert(webhook_id: str):
        """Send alert for webhook in dead letter queue"""
        webhook_doc = frappe.get_doc('Builder Webhook Log', webhook_id)

        frappe.log_error(
            f"Webhook {webhook_id} moved to dead letter queue after {webhook_doc.retry_count} retries.\n"
            f"URL: {webhook_doc.url}\n"
            f"Event: {webhook_doc.event_type}",
            "Webhook Dead Letter"
        )

    @staticmethod
    def cleanup_old_webhooks(days: int = 30):
        """
        Clean up old webhook logs
        Run via scheduler

        Args:
            days: Delete logs older than this many days
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Keep dead letter queue items regardless of age
        frappe.db.sql("""
            DELETE FROM `tabBuilder Webhook Log`
            WHERE creation < %s
            AND status != %s
        """, (cutoff_date, WebhookStatus.DEAD_LETTER.value))

        frappe.db.commit()

    @staticmethod
    def get_webhook_stats(hours: int = 24) -> Dict[str, Any]:
        """
        Get webhook delivery statistics

        Args:
            hours: Hours to look back

        Returns:
            Webhook statistics
        """
        since_time = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

        stats = frappe.db.sql("""
            SELECT
                status,
                COUNT(*) as count,
                AVG(response_time_ms) as avg_response_time,
                AVG(retry_count) as avg_retries
            FROM `tabBuilder Webhook Log`
            WHERE creation >= %s
            GROUP BY status
        """, (since_time,), as_dict=True)

        total = sum(s['count'] for s in stats)
        delivered = sum(s['count'] for s in stats if s['status'] == WebhookStatus.DELIVERED.value)
        failed = sum(s['count'] for s in stats if s['status'] in [WebhookStatus.FAILED.value, WebhookStatus.DEAD_LETTER.value])

        return {
            'period_hours': hours,
            'total_webhooks': total,
            'delivered': delivered,
            'failed': failed,
            'success_rate': round((delivered / total * 100) if total > 0 else 0, 2),
            'breakdown': stats
        }


# API endpoints

@frappe.whitelist()
def retry_webhook(webhook_id: str) -> Dict[str, Any]:
    """
    Manually retry a failed webhook

    Args:
        webhook_id: Webhook log ID

    Returns:
        Retry result
    """
    if not frappe.has_permission('Builder Settings', 'write'):
        frappe.throw("You do not have permission to retry webhooks")

    webhook_doc = frappe.get_doc('Builder Webhook Log', webhook_id)
    payload = json.loads(webhook_doc.payload_json)

    result = WebhookManager._deliver_webhook(
        webhook_id,
        webhook_doc.url,
        payload,
        webhook_doc.event_type,
        frappe.conf.get('modula_jwt_secret')
    )

    return {
        'success': result['success'],
        'webhook_id': webhook_id,
        'result': result
    }


@frappe.whitelist()
def get_webhook_logs(limit: int = 50, status: Optional[str] = None) -> Dict[str, Any]:
    """
    Get webhook logs

    Args:
        limit: Number of logs to return
        status: Filter by status

    Returns:
        Webhook logs
    """
    if not frappe.has_permission('Builder Settings', 'read'):
        frappe.throw("You do not have permission to view webhook logs")

    filters = {}
    if status:
        filters['status'] = status

    logs = frappe.get_all(
        'Builder Webhook Log',
        filters=filters,
        fields=['*'],
        order_by='creation desc',
        limit=limit
    )

    return {
        'logs': logs,
        'count': len(logs),
        'stats': WebhookManager.get_webhook_stats()
    }


@frappe.whitelist()
def get_dead_letter_queue() -> Dict[str, Any]:
    """
    Get webhooks in dead letter queue

    Returns:
        Dead letter webhooks
    """
    if not frappe.has_permission('Builder Settings', 'read'):
        frappe.throw("You do not have permission to view dead letter queue")

    dead_letters = frappe.get_all(
        'Builder Webhook Log',
        filters={'status': WebhookStatus.DEAD_LETTER.value},
        fields=['*'],
        order_by='creation desc'
    )

    return {
        'dead_letters': dead_letters,
        'count': len(dead_letters)
    }
