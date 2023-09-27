window.SW = {
    token: null,
    initSW: function (token = null) {
        this.token = token;

        if (!"serviceWorker" in navigator) {
            //service worker isn't supported
            return;
        }

        //don't use it here if you use service worker
        //for other stuff.
        if (!"PushManager" in window) {
            //push isn't supported
            return;
        }

        //register the service worker//
        navigator.serviceWorker.register('/sw.js?v4')
            .then(() => {
                //console.log('serviceWorker installed!');
                this.initPush();
            })
            .catch((err) => {
                console.log(err);
            });
    },

    initPush: function () {
        if (!navigator.serviceWorker.ready) {
            return;
        }

        new Promise(function (resolve, reject) {
            const permissionResult = Notification.requestPermission(function (result) {
                resolve(result);
            });

            if (permissionResult) {
                permissionResult.then(resolve, reject);
            }
        })
            .then((permissionResult) => {
                if (permissionResult !== 'granted') {
                    //throw new Error('We weren\'t granted permission.');
                    //console.log('We weren\'t granted permission.');
                    return false;
                }
                this.subscribeUser();
            });
    },

    subscribeUser: function () {
        if (document.querySelector('.pushSubscriptionButton')) {
            document.querySelector('.pushSubscriptionButton').style = 'display:none';
            document.querySelectorAll('.pushNotificationCheckBoxes').forEach((el) => {
                el.removeAttribute('disabled');
                el.classList.remove('!bg-surface-300');
            });
            document.querySelectorAll('.pushNotificationCheckBoxLabels').forEach((el) => {
                el.classList.remove('text-surface-500');
            });
        }
        navigator.serviceWorker.ready
            .then((registration) => {
                const subscribeOptions = {
                    userVisibleOnly: true,
                    applicationServerKey: this.urlBase64ToUint8Array(
                        'BG8VPgt0D7UGv6wMFVPeZL9tD3J+w5hfd9Gdm4b4ciyhRATe1axvjT/+Q0iho9iJ4jUuztRnSceSnklBOVxNCIA='
                    )
                };

                return registration.pushManager.subscribe(subscribeOptions);
            })
            .then((pushSubscription) => {
                //console.log('Received PushSubscription: ', JSON.stringify(pushSubscription));
                this.storePushSubscription(pushSubscription);
            });
    },

    urlBase64ToUint8Array: function (base64String) {
        let padding = '='.repeat((4 - base64String.length % 4) % 4);
        let base64 = (base64String + padding)
            .replace(/\-/g, '+')
            .replace(/_/g, '/');

        let rawData = window.atob(base64);
        let outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    },

    storePushSubscription: function (pushSubscription) {
        const token = document.querySelector('meta[name=csrf-token]')
            ? document.querySelector('meta[name=csrf-token]').getAttribute('content')
            : this.token;

        fetch('/push', {
            method: 'POST',
            body: JSON.stringify(pushSubscription),
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRF-Token': token
            }
        })
            .then((res) => {
                return res.json();
            })
            .then((res) => {
                //console.log(res)
            })
            .catch((err) => {
                console.log(err)
            });
    }
}

