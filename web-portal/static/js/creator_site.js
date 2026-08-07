(function () {
  const menuButton = document.querySelector('.menu-button');
  const menu = document.querySelector('#site-nav');
  if (menuButton && menu) {
    menuButton.addEventListener('click', function () {
      const open = menu.classList.toggle('open');
      menuButton.setAttribute('aria-expanded', String(open));
      menuButton.textContent = open ? 'Close' : 'Menu';
    });
    menu.addEventListener('click', function (event) {
      if (event.target.closest('a')) {
        menu.classList.remove('open');
        menuButton.setAttribute('aria-expanded', 'false');
        menuButton.textContent = 'Menu';
      }
    });
  }

  const flow = document.querySelector('[data-publish-flow]');
  if (!flow) return;

  const panels = Array.from(flow.querySelectorAll('[data-step-panel]'));
  const progress = Array.from(flow.querySelectorAll('[data-step-button]'));
  let current = 0;

  function updateSummary() {
    const handle = flow.querySelector('#handle')?.value.trim();
    const caption = flow.querySelector('#caption')?.value.trim();
    const mode = flow.querySelector('input[name="publish-mode"]:checked')?.value;
    const privacy = flow.querySelector('input[name="privacy"]:checked')?.value;
    const interaction = [
      ['comments', 'Comments'],
      ['duet', 'Duet'],
      ['stitch', 'Stitch']
    ].map(function (item) {
      const input = flow.querySelector('input[name="' + item[0] + '"]');
      return item[1] + (input?.checked ? ' on' : ' off');
    }).join(' · ');
    const summaries = {
      handle: handle || 'Not yet entered',
      caption: caption || 'Not yet entered',
      mode: mode === 'drafts' ? 'Upload to drafts' : mode === 'direct' ? 'Direct post' : 'Not yet selected',
      privacy: privacy === 'private' ? 'Only me' : privacy === 'friends' ? 'Friends' : privacy === 'public' ? 'Everyone' : 'Not yet selected',
      interactions: interaction,
      commercial: !flow.querySelector('input[name="commercial"]')?.checked
        ? 'Not declared'
        : [
            flow.querySelector('input[name="your-brand"]')?.checked ? 'Your brand' : '',
            flow.querySelector('input[name="branded-content"]')?.checked ? 'Branded content' : ''
          ].filter(Boolean).join(' + ') || 'Disclosure selection required'
    };
    Object.keys(summaries).forEach(function (key) {
      const target = flow.querySelector('[data-summary="' + key + '"]');
      if (target) target.textContent = summaries[key];
    });
  }

  function updateStep(index) {
    updateSummary();
    current = Math.max(0, Math.min(index, panels.length - 1));
    panels.forEach(function (panel, i) {
      panel.classList.toggle('active', i === current);
      panel.hidden = i !== current;
    });
    progress.forEach(function (button, i) {
      if (i === current) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    const heading = panels[current].querySelector('h2');
    if (heading) heading.focus({ preventScroll: true });
    window.scrollTo({ top: flow.offsetTop - 18, behavior: 'smooth' });
  }

  function setError(panel, message) {
    const error = panel.querySelector('.error-text');
    if (!error) return;
    error.textContent = message;
    error.classList.add('show');
  }

  function clearError(panel) {
    const error = panel.querySelector('.error-text');
    if (error) error.classList.remove('show');
  }

  function validatePanel(panel) {
    clearError(panel);
    const required = Array.from(panel.querySelectorAll('[required]'));
    const invalid = required.find(function (field) {
      if (field.type === 'checkbox' || field.type === 'radio') return !field.checked && field.type === 'checkbox';
      return !field.value;
    });
    if (invalid) {
      if (invalid.type === 'radio') {
        const group = panel.querySelector('[data-required-choice]');
        if (group && !panel.querySelector('[data-required-choice] input:checked')) {
          setError(panel, 'Choose an option before continuing.');
          return false;
        }
      } else {
        invalid.focus();
        setError(panel, 'Please complete the highlighted confirmation before continuing.');
        return false;
      }
    }
    const choiceGroups = Array.from(panel.querySelectorAll('[data-required-choice]'));
    const missingGroup = choiceGroups.find(function (group) { return !group.querySelector('input:checked'); });
    if (missingGroup) {
      const isPrivacy = missingGroup.getAttribute('data-required-choice') === 'privacy';
      setError(panel, isPrivacy ? 'Choose a privacy setting. There is no preselected value.' : 'Choose one option before continuing.');
      missingGroup.querySelector('input')?.focus();
      return false;
    }
    const commercialToggle = panel.querySelector('input[name="commercial"]');
    if (commercialToggle?.checked && !panel.querySelector('input[name="your-brand"]:checked, input[name="branded-content"]:checked')) {
      setError(panel, 'Select Your brand, Branded content, or both before continuing.');
      panel.querySelector('input[name="your-brand"]')?.focus();
      return false;
    }
    return true;
  }

  progress.forEach(function (button, index) {
    button.addEventListener('click', function () {
      if (index <= current || validatePanel(panels[current])) updateStep(index);
    });
  });

  flow.querySelectorAll('[data-next]').forEach(function (button) {
    button.addEventListener('click', function () {
      const panel = panels[current];
      if (validatePanel(panel)) updateStep(current + 1);
    });
  });
  flow.querySelectorAll('[data-back]').forEach(function (button) {
    button.addEventListener('click', function () { updateStep(current - 1); });
  });

  const commercial = flow.querySelector('[data-commercial-toggle]');
  const commercialDetails = flow.querySelector('[data-commercial-details]');
  if (commercial && commercialDetails) {
    commercial.addEventListener('change', function () {
      commercialDetails.classList.toggle('show', commercial.checked);
      commercialDetails.hidden = !commercial.checked;
      if (!commercial.checked) {
        commercialDetails.querySelectorAll('input').forEach(function (input) { input.checked = false; });
      }
      updateComplianceDeclaration();
    });
  }

  function updateComplianceDeclaration() {
    const declaration = flow.querySelector('[data-compliance-declaration]');
    const branded = flow.querySelector('input[name="branded-content"]')?.checked;
    if (!declaration) return;
    declaration.textContent = branded
      ? "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation."
      : "By posting, you agree to TikTok's Music Usage Confirmation.";
  }
  flow.querySelectorAll('input[name="your-brand"], input[name="branded-content"]').forEach(function (input) {
    input.addEventListener('change', updateComplianceDeclaration);
  });

  const modeInputs = flow.querySelectorAll('input[name="publish-mode"]');
  const modeLabel = flow.querySelector('[data-mode-summary]');
  modeInputs.forEach(function (input) {
    input.addEventListener('change', function () {
      if (modeLabel) modeLabel.textContent = input.value === 'drafts' ? 'Upload to drafts' : 'Direct post';
    });
  });

  const review = flow.querySelector('[data-review]');
  const status = flow.querySelector('[data-status]');
  if (review && status) {
    review.addEventListener('click', function () {
      const panel = panels[current];
      if (!validatePanel(panel)) return;
      status.classList.add('show');
      status.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      review.disabled = true;
      review.textContent = 'Confirmation recorded';
    });
  }

  updateStep(0);
}());
