// main.js — students will add JavaScript here as features are built

document.querySelectorAll('.flash-message').forEach(function (msg) {
    setTimeout(function () {
        msg.classList.add('flash-message--hidden');
        setTimeout(function () { msg.remove(); }, 600);
    }, 5000);
});
