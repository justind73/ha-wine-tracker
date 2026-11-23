/* Shared, read-only photograph details. Source metadata is untrusted text. */
/* global T, INGRESS */
function photoSourceLink(value) {
  if (typeof value !== 'string') return null;
  try {
    var url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url : null;
  } catch (_) { return null; }
}

function renderPhotoInformation(panel, info) {
  panel.replaceChildren();
  var source = info && info.source || {};
  function line(label, value) {
    if (typeof value !== 'string' || !value.trim()) return;
    var row = document.createElement('p');
    row.textContent = label + ': ' + value;
    panel.appendChild(row);
  }
  var title = document.createElement('strong');
  title.textContent = T.photo_information;
  panel.appendChild(title);
  var origin = photoSourceLink(source.url);
  line(T.photo_source, source.source_name || (origin && origin.hostname) || T.photo_unknown);
  var page = photoSourceLink(source.page_url);
  if (page) {
    var row = document.createElement('p');
    var link = document.createElement('a');
    link.textContent = T.photo_product_page;
    link.href = page.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    row.appendChild(link);
    panel.appendChild(row);
  }
  var rights = source.rights || {};
  var verified = rights.status === 'verified';
  line(T.photo_rights, verified ? T.photo_verified : T.photo_unverified);
  if (!verified) {
    var note = document.createElement('p');
    note.textContent = T.photo_unverified_note;
    panel.appendChild(note);
  }
  if (verified) line(T.photo_evidence, rights.reference);
  line(T.photo_attribution, source.attribution);
}

function addPhotoInformation(id, wine) {
  if (!wine.image) return;
  var body = document.getElementById('viewModalBody');
  var photo = body.querySelector('.view-photo-panel');
  var fields = body.querySelector('.view-fields-panel');
  if (!photo || !fields) return;
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'photo-info-button';
  button.textContent = 'ⓘ';
  button.title = T.photo_information;
  button.setAttribute('aria-label', T.photo_information);
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-controls', 'photoInformation');
  var panel = document.createElement('section');
  panel.id = 'photoInformation';
  panel.className = 'photo-information';
  panel.hidden = true;
  panel.setAttribute('aria-live', 'polite');
  fields.prepend(panel);
  photo.appendChild(button);
  button.addEventListener('click', function(event) {
    event.stopPropagation();
    panel.hidden = !panel.hidden;
    button.setAttribute('aria-expanded', String(!panel.hidden));
    if (panel.hidden) return;
    if (wine.image_info) { renderPhotoInformation(panel, wine.image_info); return; }
    panel.textContent = T.photo_loading;
    // The cellar's fallback card data may predate the detail GET.
    fetch(INGRESS + '/api/wine/' + encodeURIComponent(id))
      .then(function(response) { if (!response.ok) throw new Error(); return response.json(); })
      .then(function(data) {
        if (!data.ok || data.wine.image !== wine.image || !data.wine.image_info) throw new Error();
        wine.image_info = data.wine.image_info;
        renderPhotoInformation(panel, wine.image_info);
      })
      .catch(function() { panel.textContent = T.photo_unavailable; });
  });
}
