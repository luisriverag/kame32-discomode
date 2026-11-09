import { previewCommand, previewState } from './app.js';

const clientId = crypto.randomUUID();
const page = document.body.classList.contains('teach-page') ? 'TeachMoves' : 'DanceMode';
let polling = false;
async function json(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`Bridge request failed (${response.status}).`);
  return response.json();
}
const post = (path, value) => json(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
async function poll() {
  if (polling) return;
  polling = true;
  try {
    await post('/api/browser-clients', { client_id: clientId, page, state: previewState() });
    const commands = await json(`/api/browser-commands?client_id=${clientId}`);
    for (const command of commands) {
      let status = 'completed', result = 'Preview updated.';
      try {
        if (['record', 'stop_recording', 'select_move'].includes(command.action)) {
          const { teachAction } = await import('./teach.js');
          await teachAction(command.action, command.arguments);
        } else result = await previewCommand(command.action, command.arguments) ?? result;
      } catch (error) { status = 'failed'; result = error.message; }
      await post(`/api/browser-commands/${command.id}`, { client_id: clientId, status, result });
    }
  } catch { /* A reconnect registers again; failed deliveries expire instead of replaying. */ }
  finally { polling = false; }
}
poll();
setInterval(poll, 750);
