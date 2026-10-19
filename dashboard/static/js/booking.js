(() => {
  'use strict';
  const receipt = new URLSearchParams(location.hash.slice(1)).get('receipt');
  history.replaceState(null, '', location.pathname + location.search);
  const status = document.getElementById('booking-status');
  const form = document.getElementById('booking-form');
  const select = document.getElementById('booking-slot');
  const confirm = document.getElementById('booking-confirm');
  const copy = document.getElementById('booking-copy');
  const refresh = document.getElementById('booking-refresh');
  const localTime = value => new Date(value).toLocaleString(undefined, {dateStyle:'medium',timeStyle:'short'});
  let booking, busy = false;
  const errors = {invalid_receipt:'This booking link is invalid or expired. Contact the business.',
    slot_unavailable:'That time is no longer available. Reload your booking before choosing another time.',
    booking_changed:'Your appointment changed elsewhere. Reload before making another change.',
    booking_started:'This appointment has already started. Contact the business.',
    booking_not_changeable:'This appointment cannot be changed here. Contact the business.',
    action_unavailable:'Changes are currently unavailable. Contact the business.'};
  async function call(operation) {
    if (busy) return;
    busy = true;
    for (const button of form.querySelectorAll('button')) button.disabled = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(location.pathname, {method:'POST', credentials:'same-origin', signal:controller.signal,
        headers:{'Content-Type':'application/json', 'X-CSRF-Token':document.body.dataset.csrf}, body:JSON.stringify({tenant:document.body.dataset.tenant,
          receipt_token:receipt, operation, confirm:confirm.checked, slot_id:select.value,
          expected_slot_id:booking && booking.slot_id})});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(errors[data.error] || 'The request could not be completed. Contact the business.');
      booking = data.booking;
      status.textContent = booking.status === 'cancelled' ? 'Your appointment is cancelled.' :
        'Your appointment: ' + booking.label + ' · ' + localTime(booking.start_at) + ' · ' + booking.status;
      form.hidden = booking.status !== 'confirmed';
      select.replaceChildren(new Option('Choose a time', ''));
      for (const slot of data.slots) select.add(new Option(slot.label + ' · ' + localTime(slot.start_at), slot.id));
      confirm.checked = false;
    } catch (error) {
      status.textContent = error.name === 'AbortError' ? 'The connection timed out. Use Refresh appointment to check its current status before retrying.' : error.message;
    } finally {
      clearTimeout(timer); busy = false;
      for (const button of form.querySelectorAll('button')) button.disabled = false;
    }
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!confirm.checked) { status.textContent = 'Confirm your change using the checkbox first.'; return; }
    const operation = event.submitter.value;
    if (operation === 'reschedule' && !select.value) { status.textContent = 'Choose an available time first.'; return; }
    call(operation);
  });
  if (receipt) {
    copy.hidden = false;
    refresh.hidden = false;
    refresh.addEventListener('click', () => call('view'));
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(location.origin + location.pathname + location.search + '#receipt=' + encodeURIComponent(receipt));
        copy.textContent = 'Private link copied';
      } catch (_) { copy.textContent = 'Could not copy. Use the link in your booking confirmation.'; }
    });
    call('view');
  } else status.textContent = 'Open the private management link from your booking confirmation.';
})();
