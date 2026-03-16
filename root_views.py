import json

from django.http import HttpResponse
from django.shortcuts import redirect

from integration_utils.bitrix24.bitrix_user_auth.main_auth import main_auth


def _extract_action_params(payload):
    if not isinstance(payload, dict):
        return {}
    action = payload
    if isinstance(payload.get("actionParams"), dict):
        action = payload["actionParams"]

    target = action.get("target") or ""
    thread_id = action.get("thread_id") or ""
    mode = action.get("mode") or ""
    if isinstance(thread_id, list):
        thread_id = thread_id[0] if thread_id else ""
    if isinstance(mode, list):
        mode = mode[0] if mode else ""

    if isinstance(target, list):
        target = target[0] if target else ""

    target = str(target).strip().lower()
    thread_id = str(thread_id).strip()
    mode = str(mode).strip().lower()
    return {"target": target, "thread_id": thread_id, "mode": mode}


@main_auth(on_start=True)
def index(request):
    params = {}

    # openRestApp sends PLACEMENT_OPTIONS in POST (Bitrix side panel).
    if request.method == "POST" and hasattr(request, "POST") and "PLACEMENT_OPTIONS" in request.POST:
        try:
            placement = json.loads(request.POST["PLACEMENT_OPTIONS"])
        except Exception:
            placement = None
        params = _extract_action_params(placement)
        if params.get("thread_id") and params.get("mode") in ("view", "reply"):
            if params.get("target") == "email_activity":
                widget_mode = "compose" if params["mode"] == "reply" else "history"
                return redirect(
                    f"/email/bitrix/widget/activity/?mode={widget_mode}&thread_id={params['thread_id']}"
                )
            return redirect(f"/email/ui/{params['thread_id']}/?mode={params['mode']}")

    # When opened via Bitrix "openRestApp", Bitrix sends actionParams inside PLACEMENT_OPTIONS.
    # integration_utils.bitrix24.views.start wraps them into GET param `bx_referer_params`.
    bx = request.GET.get("bx_referer_params")
    if bx:
        try:
            data = json.loads(bx)
        except Exception:
            data = None
        params = _extract_action_params(data)
    if params.get("thread_id") and params.get("mode") in ("view", "reply"):
        if params.get("target") == "email_activity":
            widget_mode = "compose" if params["mode"] == "reply" else "history"
            return redirect(f"/email/bitrix/widget/activity/?mode={widget_mode}&thread_id={params['thread_id']}")
        return redirect(f"/email/ui/{params['thread_id']}/?mode={params['mode']}")

    # Fallback: allow opening directly with query params
    thread_id = (request.GET.get("thread_id") or "").strip()
    mode = (request.GET.get("mode") or "").strip().lower()
    if thread_id and mode in ("view", "reply"):
        return redirect(f"/email/ui/{thread_id}/?mode={mode}")

    return HttpResponse("is-rapid: ok")

