// Show active pairing requests in open Home Assistant frontend sessions.
// The source is loaded by add_extra_js_url and needs no dashboard resource.
const NOTICE_PREFIX = "ninebot_e_scooters_pair_";
const BUTTON_TITLES = ["Pairing jetzt bestätigen", "Gespeicherten Schlüssel bestätigen"];
const IMAGE_URL = "/api/ninebot_e_scooters/power_button.gif";

let subscribedConnection;
let unsubscribe;
let notices = new Map();
let dialog;
let dismissedNotice;

function currentPairingNotice() {
  return [...notices.values()].find(({ notification_id: id, title }) =>
    id?.startsWith(NOTICE_PREFIX) && BUTTON_TITLES.some((ending) => title?.includes(ending))
  );
}

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.setAttribute("aria-labelledby", "ninebot-pairing-title");
  // Explicit positioning keeps the native modal centered despite frontend styles.
  dialog.style.cssText = "position:fixed;inset:0;margin:auto;box-sizing:border-box;width:min(25rem,calc(100vw - 2rem));max-height:calc(100dvh - 2rem);overflow:auto;padding:1.5rem;border:0;border-radius:1rem;box-shadow:0 1rem 3rem #0005;color:var(--primary-text-color,#222);background:var(--card-background-color,#fff);text-align:center";
  const title = document.createElement("h2");
  title.id = "ninebot-pairing-title";
  title.textContent = "Scooter-Pairing bestätigen";
  const description = document.createElement("p");
  description.textContent = "Bitte jetzt einmal kurz die Einschalttaste am Scooter drücken. Lass den Scooter eingeschaltet.";
  const animation = document.createElement("img");
  animation.src = IMAGE_URL;
  animation.alt = "Animation: Power-Button kurz drücken";
  animation.style.cssText = "display:block;max-height:230px;max-width:100%;margin:1rem auto";
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Verstanden";
  close.style.cssText = "padding:.6rem 1rem;border:0;border-radius:.5rem;background:var(--primary-color,#03a9f4);color:white;cursor:pointer";
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    dismissedNotice = currentPairingNotice()?.notification_id;
  });
  dialog.append(title, description, animation, close);
  document.body.append(dialog);
  return dialog;
}

function refreshDialog() {
  const notice = currentPairingNotice();
  if (!notice) {
    dismissedNotice = undefined;
    if (dialog?.open) dialog.close();
    return;
  }
  if (document.visibilityState === "hidden" || dismissedNotice === notice.notification_id) return;
  const view = ensureDialog();
  if (!view.open) view.showModal();
}

function handleNotificationStream(event) {
  if (event.type === "current") notices = new Map();
  for (const [id, notice] of Object.entries(event.notifications || {})) {
    if (!id.startsWith(NOTICE_PREFIX)) continue;
    if (event.type === "removed") notices.delete(id);
    else notices.set(id, { ...notice, notification_id: id });
  }
  refreshDialog();
}

function findFrontendConnection() {
  return document.querySelector("home-assistant")?.hass?.connection;
}

function subscribeWhenReady() {
  if (!document.body) return;
  const connection = findFrontendConnection();
  if (!connection || connection === subscribedConnection || connection.connected === false) return;
  unsubscribe?.();
  subscribedConnection = connection;
  void connection.subscribeMessage(
    handleNotificationStream,
    { type: "persistent_notification/subscribe" }
  ).then((stop) => {
    if (subscribedConnection === connection) unsubscribe = stop;
    else stop();
  }).catch(() => {
    if (subscribedConnection === connection) subscribedConnection = undefined;
  });
}

document.addEventListener("visibilitychange", refreshDialog);
// Frontend startup and WebSocket reconnect are asynchronous; checking the
// local DOM does not contact the scooter or cause another Bluetooth beep.
setInterval(subscribeWhenReady, 1000);
subscribeWhenReady();
