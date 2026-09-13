// One-shot KWin 6 placement, with an independent expiry if the controller dies.
const source = workspace.activeWindow ? workspace.activeWindow.output : workspace.activeScreen;
const sourceName = source ? source.name : "";
let stopped = false;
let targetWindow = null;
let targetName = "";
const verification = new QTimer();
verification.interval = 50;
const expiry = new QTimer();
expiry.singleShot = true;
expiry.interval = config.expiry;
function stop() {
    if (stopped) return;
    stopped = true;
    workspace.windowAdded.disconnect(place);
    expiry.stop();
    verification.stop();
}
function acknowledge(name) {
    callDBus("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", name);
}
function place(window) {
    if (stopped || targetWindow || String(window.resourceClass) !== config.appId) return;
    // Re-read outputs for hotplug, but retain the source from before launch.
    const outputs = Array.from(workspace.screens).sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    if (!outputs.length) { stop(); return; }
    const index = outputs.findIndex(output => output.name === sourceName);
    const target = outputs[(index + 1) % outputs.length];
    targetWindow = window;
    targetName = target.name;
    workspace.sendClientToScreen(window, target);
    window.setMaximize(true, true);
    verification.start();
}
verification.timeout.connect(function () {
    if (targetWindow && targetWindow.output && targetWindow.output.name === targetName
            && targetWindow.maximizeMode === 3) {
        stop();
        acknowledge(config.done);
    }
});
workspace.windowRemoved.connect(function (window) {
    if (window === targetWindow) { targetWindow = null; stop(); }
});
workspace.windowAdded.connect(place);
expiry.timeout.connect(stop);
expiry.start();
acknowledge(config.ready);
