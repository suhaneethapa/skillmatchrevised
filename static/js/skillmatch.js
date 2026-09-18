/* SkillMatch — minimal site-wide JavaScript.
   Only what the interface genuinely needs: tab switching on the register
   page, dismissible alert messages, and the mobile navigation toggle. */

document.addEventListener("DOMContentLoaded", function () {
    // Dismissible alert messages
    document.querySelectorAll("[data-dismiss]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var alert = btn.closest(".sm-alert");
            if (alert) alert.remove();
        });
    });

    // Mobile navigation toggle
    var toggle = document.getElementById("smNavToggle");
    var nav = document.getElementById("smNav");
    if (toggle && nav) {
        toggle.addEventListener("click", function () {
            nav.classList.toggle("open");
        });
    }

    // Role tabs on the register page
    document.querySelectorAll("[data-tab]").forEach(function (tab) {
        tab.addEventListener("click", function () {
            var group = tab.closest("[data-tabs]");
            if (!group) return;
            group.querySelectorAll("[data-tab]").forEach(function (t) {
                t.classList.toggle("active", t === tab);
            });
            group.querySelectorAll("[data-tab-panel]").forEach(function (panel) {
                panel.classList.toggle(
                    "active",
                    panel.getAttribute("data-tab-panel") === tab.getAttribute("data-tab")
                );
            });
        });
    });
});
