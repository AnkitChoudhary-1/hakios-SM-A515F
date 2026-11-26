import pathlib
import sys

p_app = pathlib.Path(r'\\wsl$\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios\userland\src\inject_app.c')
app_text = p_app.read_text(encoding='utf-8')

# Ensure touch_lat=0 in prepare_boot.py
p_prep = pathlib.Path('outputs/scripts/prepare_boot.py')
prep_text = p_prep.read_text(encoding='utf-8')
if 'touch_lat=1' in prep_text:
    prep_text = prep_text.replace('touch_lat=1', 'touch_lat=0')
    p_prep.write_text(prep_text, encoding='utf-8')
    print("Ensured touch_lat=0 in prepare_boot.py")

# Ensure headers at top of inject_app.c
headers_to_prepend = '''#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <SystemConfiguration/SystemConfiguration.h>
#include <SystemConfiguration/SCNetworkReachability.h>
#include <Network/Network.h>
#include <dlfcn.h>
'''

if '#include <CoreFoundation/CoreFoundation.h>' not in app_text:
    app_text = headers_to_prepend + app_text
    print("Prepended CoreFoundation, Security, SystemConfiguration, Network headers")

# Now apply keychain + reachability + NUX transition code from begin_task to end of file
start_marker = "static unsigned long (*begin_task)(id, SEL, id);"
assert start_marker in app_text, "start_marker not found"
start_pos = app_text.find(start_marker)

replacement = '''static unsigned long (*begin_task)(id, SEL, id);
static unsigned long (*begin_task_name)(id, SEL, id, id);
static void (*resume_task)(id, SEL);

static inline Boolean
responds_to(id obj, const char *sel_name)
{
	if (!obj) return false;
	Boolean (*resp)(id, SEL, SEL) = (Boolean (*)(id, SEL, SEL))objc_msgSend;
	return resp(obj, sel_registerName("respondsToSelector:"), sel_registerName(sel_name));
}

static unsigned long
watched_begin_task(id self, SEL cmd, id handler)
{
	unsigned long task;
	char line[160];
	int n;

	n = snprintf(line, sizeof(line), "hakios: %s: asking UIKit for a background task\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
	task = begin_task ? begin_task(self, cmd, handler) : 101;
	n = snprintf(line, sizeof(line), "hakios: %s: the background task is %lu\\n", who, task);
	say(line, (size_t)(n > 0 ? n : 0));
	return task;
}

static unsigned long
watched_begin_task_name(id self, SEL cmd, id task_name, id handler)
{
	unsigned long task;
	char line[200];
	const char *(*utf8)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	const char *name = task_name && utf8 ? utf8(task_name, sel_registerName("UTF8String")) : "?";
	int n;

	n = snprintf(line, sizeof(line), "hakios: %s: asking UIKit for background task '%s'\\n", who, name ? name : "?");
	say(line, (size_t)(n > 0 ? n : 0));
	task = begin_task_name ? begin_task_name(self, cmd, task_name, handler) : 102;
	n = snprintf(line, sizeof(line), "hakios: %s: background task '%s' is %lu\\n", who, name ? name : "?", task);
	say(line, (size_t)(n > 0 ? n : 0));
	return task;
}

static void
watched_resume_task(id self, SEL cmd)
{
	char line[256];
	id (*req)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	id (*url)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	const char *(*utf8)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	id current_req = req ? req(self, sel_registerName("currentRequest")) : nil;
	id req_url = (current_req && url) ? url(current_req, sel_registerName("URL")) : nil;
	id abs_str = (req_url && req) ? req(req_url, sel_registerName("absoluteString")) : nil;
	const char *url_str = (abs_str && utf8) ? utf8(abs_str, sel_registerName("UTF8String")) : "?";
	int n = snprintf(line, sizeof(line), "hakios: %s: NSURLSessionTask resume: %s\\n", who, url_str ? url_str : "?");
	say(line, (size_t)(n > 0 ? n : 0));
	if (resume_task) {
		resume_task(self, cmd);
	}
}

/* UserNotifications hooks */
typedef void (^UNAuthCompletionHandler)(Boolean granted, id error);
static void (*orig_un_req)(id, SEL, unsigned long long, id);

static void
watched_un_request_auth(id self, SEL cmd, unsigned long long options, id handler)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: UNUserNotificationCenter requestAuthorizationWithOptions:%llu called\\n",
	    who, options);
	say(line, (size_t)(n > 0 ? n : 0));

	if (handler != NULL) {
		UNAuthCompletionHandler block = (UNAuthCompletionHandler)Block_copy(handler);
		dispatch_async(dispatch_get_main_queue(), ^{
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-granting UNUserNotificationCenter authorization!\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			block(true, NULL);
			Block_release(block);
		});
	}
}

typedef void (^UNSettingsBlock)(id settings);

static void
watched_un_get_settings(id self, SEL cmd, id handler)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: UNUserNotificationCenter getNotificationSettingsWithCompletionHandler called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));

	if (handler != NULL) {
		UNSettingsBlock block = (UNSettingsBlock)Block_copy(handler);
		dispatch_async(dispatch_get_main_queue(), ^{
			Class cls = objc_getClass("UNNotificationSettings");
			id settings = cls ? ((id (*)(id, SEL))objc_msgSend)(((id (*)(id, SEL))objc_msgSend)(cls, sel_registerName("alloc")), sel_registerName("init")) : nil;
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-invoking getNotificationSettings handler (settings=%p)\\n", who, (void*)settings);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			block(settings);
			Block_release(block);
		});
	}
}

static long long
watched_un_settings_auth_status(id self, SEL cmd)
{
	return 2; /* UNAuthorizationStatusAuthorized */
}

static long long
watched_un_settings_enabled(id self, SEL cmd)
{
	return 1; /* UNNotificationSettingEnabled */
}

static long long
watched_un_settings_alert_style(id self, SEL cmd)
{
	return 2; /* UNAlertStyleBanner */
}

/* Contacts hooks */
typedef void (^CNAccessCompletionHandler)(Boolean granted, id error);
static void (*orig_cn_req)(id, SEL, long, id);

static void
watched_cn_request_access(id self, SEL cmd, long entityType, id handler)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: CNContactStore requestAccessForEntityType:%ld called\\n",
	    who, entityType);
	say(line, (size_t)(n > 0 ? n : 0));

	if (handler != NULL) {
		CNAccessCompletionHandler block = (CNAccessCompletionHandler)Block_copy(handler);
		dispatch_async(dispatch_get_main_queue(), ^{
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-answering CNContactStore access (true)!\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			block(true, NULL);
			Block_release(block);
		});
	}
}

static long
watched_cn_auth_status(id self, SEL cmd, long entityType)
{
	return 3; /* CNAuthorizationStatusAuthorized */
}

/* CoreLocation hooks */
static Boolean
watched_cl_location_services_enabled(id self, SEL cmd)
{
	return true;
}

static int
watched_cl_auth_status(id self, SEL cmd)
{
	return 3; /* kCLAuthorizationStatusAuthorizedWhenInUse */
}

static int
watched_cl_accuracy_auth(id self, SEL cmd)
{
	return 0; /* CLAccuracyAuthorizationFullAccuracy */
}

static void
watched_cl_request_when_in_use(id self, SEL cmd)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: CLLocationManager requestWhenInUseAuthorization called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));

	id (*get_del)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	id delegate = get_del ? get_del(self, sel_registerName("delegate")) : nil;
	if (delegate) {
		dispatch_async(dispatch_get_main_queue(), ^{
			void (*send_auth)(id, SEL, id) = (void (*)(id, SEL, id))objc_msgSend;
			void (*send_status)(id, SEL, id, int) = (void (*)(id, SEL, id, int))objc_msgSend;
			if (responds_to(delegate, "locationManagerDidChangeAuthorization:")) {
				send_auth(delegate, sel_registerName("locationManagerDidChangeAuthorization:"), self);
			}
			if (responds_to(delegate, "locationManager:didChangeAuthorizationStatus:")) {
				send_status(delegate, sel_registerName("locationManager:didChangeAuthorizationStatus:"), self, 3);
			}
		});
	}
}

static void
watched_cl_request_always(id self, SEL cmd)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: CLLocationManager requestAlwaysAuthorization called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));

	id (*get_del)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	id delegate = get_del ? get_del(self, sel_registerName("delegate")) : nil;
	if (delegate) {
		dispatch_async(dispatch_get_main_queue(), ^{
			void (*send_auth)(id, SEL, id) = (void (*)(id, SEL, id))objc_msgSend;
			void (*send_status)(id, SEL, id, int) = (void (*)(id, SEL, id, int))objc_msgSend;
			if (responds_to(delegate, "locationManagerDidChangeAuthorization:")) {
				send_auth(delegate, sel_registerName("locationManagerDidChangeAuthorization:"), self);
			}
			if (responds_to(delegate, "locationManager:didChangeAuthorizationStatus:")) {
				send_status(delegate, sel_registerName("locationManager:didChangeAuthorizationStatus:"), self, 3);
			}
		});
	}
}

static void
watched_cl_start_updating_location(id self, SEL cmd)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: CLLocationManager startUpdatingLocation called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
}

/* AppTrackingTransparency hooks */
typedef void (^ATTCompletionHandler)(unsigned long status);

static void
watched_att_request(id self, SEL cmd, id completion)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: ATTrackingManager requestTrackingAuthorization called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
	if (completion) {
		ATTCompletionHandler copied = (ATTCompletionHandler)Block_copy(completion);
		dispatch_async(dispatch_get_main_queue(), ^{
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-answering ATTrackingManager (Authorized)\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			copied(3); /* ATTrackingManagerAuthorizationStatusAuthorized */
			Block_release(copied);
		});
	}
}

/* AVFoundation & Photos hooks */
typedef void (^AVAccessCompletionHandler)(Boolean granted);

static void
watched_av_request_access(id self, SEL cmd, id mediaType, id handler)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: AVCaptureDevice requestAccessForMediaType called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
	if (handler) {
		AVAccessCompletionHandler copied = (AVAccessCompletionHandler)Block_copy(handler);
		dispatch_async(dispatch_get_main_queue(), ^{
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-granting AVCaptureDevice access\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			copied(true);
			Block_release(copied);
		});
	}
}

typedef void (^PHAuthCompletionHandler)(long status);

static void
watched_ph_request_auth(id self, SEL cmd, id handler)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: PHPhotoLibrary requestAuthorization called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
	if (handler) {
		PHAuthCompletionHandler copied = (PHAuthCompletionHandler)Block_copy(handler);
		dispatch_async(dispatch_get_main_queue(), ^{
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-granting PHPhotoLibrary authorization\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			copied(3); /* PHAuthorizationStatusAuthorized */
			Block_release(copied);
		});
	}
}

static void
watched_ph_request_auth_level(id self, SEL cmd, long level, id handler)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: PHPhotoLibrary requestAuthorizationForAccessLevel:%ld called\\n", who, level);
	say(line, (size_t)(n > 0 ? n : 0));
	if (handler) {
		PHAuthCompletionHandler copied = (PHAuthCompletionHandler)Block_copy(handler);
		dispatch_async(dispatch_get_main_queue(), ^{
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-granting PHPhotoLibrary access level\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			copied(3); /* PHAuthorizationStatusAuthorized */
			Block_release(copied);
		});
	}
}

/* Instagram specific IGNetworkInfo hooks */
static Boolean
watched_IGNetworkInfo_isOnWifiNetwork(id self, SEL cmd)
{
	return true;
}

static Boolean
watched_IGNetworkInfo_isReachableViaWiFi(id self, SEL cmd)
{
	return true;
}

static Boolean
watched_IGNetworkInfo_isReachableViaWWAN(id self, SEL cmd)
{
	return false;
}

static id
watched_IGNetworkInfo_connectionTypeString(id self, SEL cmd)
{
	return (id)CFSTR("wifi");
}

static id
watched_IGNetworkInfo_fbConnectionTypeString(id self, SEL cmd)
{
	return (id)CFSTR("WIFI");
}

static id
watched_IGNetworkInfo_networkReachabilityStatus(id self, SEL cmd)
{
	return (id)CFSTR("ReachableViaWiFi");
}

/* Instagram NUX Transition View Controller auto-advancement hook */
static void (*orig_trans_view_did_appear)(id, SEL, Boolean);
static void
watched_trans_view_did_appear(id self, SEL cmd, Boolean animated)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: IGSessionlessNUXTransitionViewController viewDidAppear!\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
	if (orig_trans_view_did_appear) {
		orig_trans_view_did_appear(self, cmd, animated);
	}
	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(500 * NSEC_PER_MSEC)), dispatch_get_main_queue(), ^{
		id (*get_del)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
		id delegate = get_del ? get_del(self, sel_registerName("delegate")) : nil;
		char l2[256];
		int n2 = snprintf(l2, sizeof(l2), "hakios: %s: IGSessionlessNUXTransitionViewController completing transition (delegate=%p)!\\n", who, (void*)delegate);
		say(l2, (size_t)(n2 > 0 ? n2 : 0));
		if (delegate) {
			if (responds_to(delegate, "transitionViewControllerDidCompleteTimer")) {
				void (*send_timer)(id, SEL) = (void (*)(id, SEL))objc_msgSend;
				send_timer(delegate, sel_registerName("transitionViewControllerDidCompleteTimer"));
			}
		}
	});
}

/* Instagram Location Services Upsell auto-dismiss hook */
static void (*orig_loc_view_did_appear)(id, SEL, Boolean);
static void
watched_loc_view_did_appear(id self, SEL cmd, Boolean animated)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: IGNUXLocationServicesViewController viewDidAppear!\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
	if (orig_loc_view_did_appear) {
		orig_loc_view_did_appear(self, cmd, animated);
	}
	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(300 * NSEC_PER_MSEC)), dispatch_get_main_queue(), ^{
		id (*get_del)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
		id delegate = get_del ? get_del(self, sel_registerName("delegate")) : nil;
		if (delegate) {
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-dismissing IGNUXLocationServices (delegate=%p)\\n", who, (void*)delegate);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			if (responds_to(delegate, "locationServicesUpsellViewDidTapDismissButton:")) {
				void (*dismiss_fn)(id, SEL, id) = (void (*)(id, SEL, id))objc_msgSend;
				dismiss_fn(delegate, sel_registerName("locationServicesUpsellViewDidTapDismissButton:"), nil);
			}
		}
	});
}

static void
keep_to_the_repositories(void)
{
	CFPreferencesSetAppValue(CFSTR("ShowProvisional"), kCFBooleanFalse, CFSTR("org.coolstar.SileoStore"));
	CFPreferencesAppSynchronize(CFSTR("org.coolstar.SileoStore"));
}

static void (*move_url)(id, SEL, id, id, id *);
static void (*copy_url)(id, SEL, id, id, id *);
static void (*move_path)(id, SEL, id, id, id *);
static void (*copy_path)(id, SEL, id, id, id *);

static void
show_error(const char *name, id error)
{
	id (*desc)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	const char *(*utf8)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	id str = error != NULL ? desc(error, sel_registerName("localizedDescription")) : NULL;
	const char *s = str != NULL ? utf8(str, sel_registerName("UTF8String")) : NULL;
	char line[500];
	int n = snprintf(line, sizeof(line), "hakios: %s: NSFileManager %s: %s\\n", who, name, s != NULL ? s : "(null)");

	say(line, (size_t)(n > 0 ? n : 0));
}

static void
watched_move_url(id self, SEL cmd, id from, id to, id *error)
{
	move_url(self, cmd, from, to, error);
	if (error != NULL && *error != NULL) {
		show_error("moveItemAtURL", *error);
	}
}

static void
watched_copy_url(id self, SEL cmd, id from, id to, id *error)
{
	copy_url(self, cmd, from, to, error);
	if (error != NULL && *error != NULL) {
		show_error("copyItemAtURL", *error);
	}
}

static void
watched_move_path(id self, SEL cmd, id from, id to, id *error)
{
	move_path(self, cmd, from, to, error);
	if (error != NULL && *error != NULL) {
		show_error("moveItemAtPath", *error);
	}
}

static void
watched_copy_path(id self, SEL cmd, id from, id to, id *error)
{
	copy_path(self, cmd, from, to, error);
	if (error != NULL && *error != NULL) {
		show_error("copyItemAtPath", *error);
	}
}

static int
watched_spawn(pid_t *pid, const char *path, const posix_spawn_file_actions_t *actions,
    const posix_spawnattr_t *attr, char *const argv[], char *const envp[])
{
	static const char *const deny[] = {
		"/usr/bin/dpkg",
		"/usr/bin/dpkg-deb",
		"/redwood/bin/dpkg",
		"/redwood/bin/dpkg-deb",
	};
	char line[500];
	int n;

	for (unsigned i = 0; i < sizeof(deny) / sizeof(deny[0]); i++) {
		if (strcmp(path, deny[i]) == 0) {
			n = snprintf(line, sizeof(line),
			    "hakios: %s: denying posix_spawn(%s) so the prefix does not break itself\\n", who, path);
			say(line, (size_t)(n > 0 ? n : 0));
			return EPERM;
		}
	}
	return posix_spawn(pid, path, actions, attr, argv, envp);
}

/*
 * Fallback keychain cache for third-party apps running without entitlements.
 * In stock iOS without proper entitlements or daemon, SecItemCopyMatching,
 * SecItemAdd, and SecItemUpdate fail with -34018 (errSecMissingEntitlement).
 * We maintain an in-memory & file-backed fallback cache so credentials persist
 * across app launches and login sessions.
 */
static CFMutableArrayRef g_keychain_cache = NULL;
static const char *g_keychain_file = "/private/var/mobile/Library/Preferences/com.hakios.keychain_fallback.plist";

static void
apply_dict_entry(const void *key, const void *val, void *context)
{
	CFMutableDictionaryRef target = (CFMutableDictionaryRef)context;
	CFDictionarySetValue(target, key, val);
}

static void
init_keychain_cache(void)
{
	if (g_keychain_cache != NULL) {
		return;
	}
	CFURLRef file_url = CFURLCreateFromFileSystemRepresentation(kCFAllocatorDefault,
	    (const UInt8 *)g_keychain_file, strlen(g_keychain_file), false);
	if (file_url) {
		CFReadStreamRef stream = CFReadStreamCreateWithFile(kCFAllocatorDefault, file_url);
		if (stream && CFReadStreamOpen(stream)) {
			CFPropertyListRef plist = CFPropertyListCreateWithStream(kCFAllocatorDefault, stream,
			    0, kCFPropertyListMutableContainersAndLeaves, NULL, NULL);
			if (plist && CFGetTypeID(plist) == CFArrayGetTypeID()) {
				g_keychain_cache = (CFMutableArrayRef)plist;
			}
			CFReadStreamClose(stream);
		}
		if (stream) CFRelease(stream);
		CFRelease(file_url);
	}
	if (g_keychain_cache == NULL) {
		g_keychain_cache = CFArrayCreateMutable(kCFAllocatorDefault, 0, &kCFTypeArrayCallBacks);
	}
}

static void
save_keychain_cache(void)
{
	if (g_keychain_cache == NULL) {
		return;
	}
	mkdir("/private/var/mobile/Library/Preferences", 0755);
	CFURLRef file_url = CFURLCreateFromFileSystemRepresentation(kCFAllocatorDefault,
	    (const UInt8 *)g_keychain_file, strlen(g_keychain_file), false);
	if (file_url) {
		CFWriteStreamRef stream = CFWriteStreamCreateWithFile(kCFAllocatorDefault, file_url);
		if (stream && CFWriteStreamOpen(stream)) {
			CFPropertyListWrite(g_keychain_cache, stream, kCFPropertyListBinaryFormat_v1_0, 0, NULL);
			CFWriteStreamClose(stream);
		}
		if (stream) CFRelease(stream);
		CFRelease(file_url);
	}
}

static CFDataRef
make_persistent_ref(CFDictionaryRef dict)
{
	CFStringRef service = CFDictionaryGetValue(dict, kSecAttrService);
	CFStringRef account = CFDictionaryGetValue(dict, kSecAttrAccount);
	if (!service) {
		service = CFDictionaryGetValue(dict, kSecAttrServer);
	}
	if (!service) {
		service = CFSTR("unknown_service");
	}
	if (!account) {
		account = CFSTR("unknown_account");
	}
	char buf[256];
	CFStringGetCString(service, buf, sizeof(buf), kCFStringEncodingUTF8);
	char buf2[256];
	CFStringGetCString(account, buf2, sizeof(buf2), kCFStringEncodingUTF8);
	char combined[512];
	int len = snprintf(combined, sizeof(combined), "%s:%s", buf, buf2);
	return CFDataCreate(kCFAllocatorDefault, (const UInt8 *)combined, len > 0 ? len : 0);
}

static Boolean
item_matches_query(CFDictionaryRef item, CFDictionaryRef query)
{
	const void *keys[] = {
		kSecClass,
		kSecAttrAccount,
		kSecAttrService,
		kSecAttrServer,
		kSecAttrAccessGroup
	};
	for (unsigned i = 0; i < sizeof(keys) / sizeof(keys[0]); i++) {
		const void *q_val = CFDictionaryGetValue(query, keys[i]);
		if (q_val != NULL) {
			const void *i_val = CFDictionaryGetValue(item, keys[i]);
			if (i_val == NULL || !CFEqual(q_val, i_val)) {
				return false;
			}
		}
	}
	return true;
}

static CFDictionaryRef
build_query_result_item(CFDictionaryRef item, CFDictionaryRef query)
{
	Boolean returnData = CFDictionaryContainsKey(query, kSecReturnData) &&
	    CFBooleanGetValue((CFBooleanRef)CFDictionaryGetValue(query, kSecReturnData));
	Boolean returnAttributes = CFDictionaryContainsKey(query, kSecReturnAttributes) &&
	    CFBooleanGetValue((CFBooleanRef)CFDictionaryGetValue(query, kSecReturnAttributes));
	Boolean returnRef = CFDictionaryContainsKey(query, kSecReturnPersistentRef) &&
	    CFBooleanGetValue((CFBooleanRef)CFDictionaryGetValue(query, kSecReturnPersistentRef));

	if (returnData && !returnAttributes && !returnRef) {
		CFDataRef data = CFDictionaryGetValue(item, kSecValueData);
		return data ? (CFDictionaryRef)CFRetain(data) : NULL;
	}
	if (returnRef && !returnData && !returnAttributes) {
		return (CFDictionaryRef)make_persistent_ref(item);
	}

	CFMutableDictionaryRef result = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, item);
	if (result) {
		if (returnRef) {
			CFDataRef pref = make_persistent_ref(item);
			if (pref) {
				CFDictionarySetValue(result, kSecValuePersistentRef, pref);
				CFRelease(pref);
			}
		}
		if (!returnData) {
			CFDictionaryRemoveValue(result, kSecValueData);
		}
	}
	return result;
}

static OSStatus
watched_SecItemCopyMatching(CFDictionaryRef query, CFTypeRef *result)
{
	OSStatus status = SecItemCopyMatching(query, result);
	char line[512];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemCopyMatching returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));

	if (query) {
		CFStringRef cls = CFDictionaryGetValue(query, kSecClass);
		CFStringRef svc = CFDictionaryGetValue(query, kSecAttrService);
		if (!svc) svc = CFDictionaryGetValue(query, kSecAttrServer);
		CFStringRef acc = CFDictionaryGetValue(query, kSecAttrAccount);
		char c_buf[64] = "?", s_buf[128] = "?", a_buf[128] = "?";
		if (cls) CFStringGetCString(cls, c_buf, sizeof(c_buf), kCFStringEncodingUTF8);
		if (svc) CFStringGetCString(svc, s_buf, sizeof(s_buf), kCFStringEncodingUTF8);
		if (acc) CFStringGetCString(acc, a_buf, sizeof(a_buf), kCFStringEncodingUTF8);
		n = snprintf(line, sizeof(line), "hakios: %s: SecItemCopyMatching query: cls=%s svc/srvr='%s' acc='%s'\\n",
		    who, c_buf, s_buf, a_buf);
		say(line, (size_t)(n > 0 ? n : 0));
	}

	if (status != errSecSuccess) {
		init_keychain_cache();
		Boolean returnData = CFDictionaryContainsKey(query, kSecReturnData) &&
		    CFBooleanGetValue((CFBooleanRef)CFDictionaryGetValue(query, kSecReturnData));
		Boolean returnAttributes = CFDictionaryContainsKey(query, kSecReturnAttributes) &&
		    CFBooleanGetValue((CFBooleanRef)CFDictionaryGetValue(query, kSecReturnAttributes));
		Boolean returnRef = CFDictionaryContainsKey(query, kSecReturnPersistentRef) &&
		    CFBooleanGetValue((CFBooleanRef)CFDictionaryGetValue(query, kSecReturnPersistentRef));
		const void *matchLimit = CFDictionaryGetValue(query, kSecMatchLimit);
		Boolean matchAll = (matchLimit && CFEqual(matchLimit, kSecMatchLimitAll));

		CFMutableArrayRef matches = CFArrayCreateMutable(kCFAllocatorDefault, 0, &kCFTypeArrayCallBacks);
		CFIndex count = CFArrayGetCount(g_keychain_cache);
		for (CFIndex i = 0; i < count; i++) {
			CFDictionaryRef item = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
			if (item_matches_query(item, query)) {
				CFTypeRef resItem = build_query_result_item(item, query);
				if (resItem) {
					CFArrayAppendValue(matches, resItem);
					CFRelease(resItem);
				}
				if (!matchAll) break;
			}
		}

		CFIndex num_matches = CFArrayGetCount(matches);
		if (num_matches > 0) {
			n = snprintf(line, sizeof(line), "hakios: %s: SecItemCopyMatching satisfied from fallback cache! (found %ld)\\n",
			    who, num_matches);
			say(line, (size_t)(n > 0 ? n : 0));
			if (result != NULL) {
				if (matchAll) {
					*result = (CFTypeRef)CFRetain(matches);
				} else {
					*result = (CFTypeRef)CFRetain(CFArrayGetValueAtIndex(matches, 0));
				}
			}
			CFRelease(matches);
			return errSecSuccess;
		}
		CFRelease(matches);
	}
	return status;
}

static OSStatus
watched_SecItemAdd(CFDictionaryRef attributes, CFTypeRef *result)
{
	OSStatus status = SecItemAdd(attributes, result);
	char line[512];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemAdd returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));

	init_keychain_cache();
	CFIndex count = CFArrayGetCount(g_keychain_cache);
	for (CFIndex i = 0; i < count; i++) {
		CFDictionaryRef existing = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
		if (item_matches_query(existing, attributes)) {
			CFArrayRemoveValueAtIndex(g_keychain_cache, i);
			break;
		}
	}

	CFMutableDictionaryRef copy = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, attributes);
	CFArrayAppendValue(g_keychain_cache, copy);
	CFRelease(copy);
	save_keychain_cache();

	n = snprintf(line, sizeof(line), "hakios: %s: SecItemAdd saved item in persistent fallback cache!\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));

	if (status != errSecSuccess) {
		if (result != NULL) {
			*result = make_persistent_ref(attributes);
		}
		return errSecSuccess;
	}
	return status;
}

static OSStatus
watched_SecItemUpdate(CFDictionaryRef query, CFDictionaryRef attributesToUpdate)
{
	OSStatus status = SecItemUpdate(query, attributesToUpdate);
	char line[512];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemUpdate returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));

	init_keychain_cache();
	CFIndex count = CFArrayGetCount(g_keychain_cache);
	Boolean updated = false;
	for (CFIndex i = 0; i < count; i++) {
		CFDictionaryRef item = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
		if (item_matches_query(item, query)) {
			CFMutableDictionaryRef mut = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, item);
			if (mut) {
				if (attributesToUpdate) {
					CFDictionaryApplyFunction(attributesToUpdate, (CFDictionaryApplierFunction)apply_dict_entry, mut);
				}
				CFArraySetValueAtIndex(g_keychain_cache, i, mut);
				CFRelease(mut);
				updated = true;
			}
			break;
		}
	}
	if (updated) {
		save_keychain_cache();
		n = snprintf(line, sizeof(line), "hakios: %s: SecItemUpdate updated item in persistent fallback cache!\\n", who);
		say(line, (size_t)(n > 0 ? n : 0));
		if (status != errSecSuccess) return errSecSuccess;
	}
	return status;
}

static OSStatus
watched_SecItemDelete(CFDictionaryRef query)
{
	OSStatus status = SecItemDelete(query);
	char line[512];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemDelete returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));

	init_keychain_cache();
	CFIndex count = CFArrayGetCount(g_keychain_cache);
	Boolean removed = false;
	for (CFIndex i = count - 1; i >= 0; i--) {
		CFDictionaryRef item = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
		if (item_matches_query(item, query)) {
			CFArrayRemoveValueAtIndex(g_keychain_cache, i);
			removed = true;
		}
	}
	if (removed) {
		save_keychain_cache();
		n = snprintf(line, sizeof(line), "hakios: %s: SecItemDelete removed item from persistent fallback cache!\\n", who);
		say(line, (size_t)(n > 0 ? n : 0));
		if (status != errSecSuccess) return errSecSuccess;
	}
	return status;
}

/* SystemConfiguration & Network reachability interpositions */
typedef struct {
	SCNetworkReachabilityRef target;
	SCNetworkReachabilityCallBack callback;
	SCNetworkReachabilityContext context;
	dispatch_queue_t queue;
	CFRunLoopRef runLoop;
	CFStringRef runLoopMode;
} tracked_reachability_t;

static tracked_reachability_t g_reachabilities[16];
static int g_num_reachabilities = 0;

static Boolean
watched_SCNetworkReachabilityGetFlags(SCNetworkReachabilityRef target, SCNetworkReachabilityFlags *flags)
{
	if (flags != NULL) {
		*flags = kSCNetworkReachabilityFlagsReachable |
		         kSCNetworkReachabilityFlagsIsDirect;
	}
	return true;
}

static Boolean
watched_SCNetworkReachabilitySetCallback(SCNetworkReachabilityRef target,
    SCNetworkReachabilityCallBack callout, SCNetworkReachabilityContext *context)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: SCNetworkReachabilitySetCallback registered (%p)\\n", who, (void*)callout);
	say(line, (size_t)(n > 0 ? n : 0));

	for (int i = 0; i < g_num_reachabilities; i++) {
		if (g_reachabilities[i].target == target) {
			g_reachabilities[i].callback = callout;
			if (context) g_reachabilities[i].context = *context;
			return true;
		}
	}
	if (g_num_reachabilities < 16) {
		g_reachabilities[g_num_reachabilities].target = target;
		g_reachabilities[g_num_reachabilities].callback = callout;
		if (context) g_reachabilities[g_num_reachabilities].context = *context;
		g_reachabilities[g_num_reachabilities].queue = NULL;
		g_reachabilities[g_num_reachabilities].runLoop = NULL;
		g_num_reachabilities++;
	}
	return true;
}

static Boolean
watched_SCNetworkReachabilitySetDispatchQueue(SCNetworkReachabilityRef target, dispatch_queue_t queue)
{
	SCNetworkReachabilityCallBack cb = NULL;
	void *info = NULL;

	for (int i = 0; i < g_num_reachabilities; i++) {
		if (g_reachabilities[i].target == target) {
			g_reachabilities[i].queue = queue;
			cb = g_reachabilities[i].callback;
			info = g_reachabilities[i].context.info;
			break;
		}
	}

	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: SCNetworkReachabilitySetDispatchQueue (queue=%p, cb=%p)\\n",
	    who, (void*)queue, (void*)cb);
	say(line, (size_t)(n > 0 ? n : 0));

	if (queue && cb) {
		dispatch_async(queue, ^{
			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: dispatching SCNetworkReachability callback (reachable)\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			SCNetworkReachabilityFlags flags = kSCNetworkReachabilityFlagsReachable | kSCNetworkReachabilityFlagsIsDirect;
			cb(target, flags, info);
		});
	}
	return true;
}

static Boolean
watched_SCNetworkReachabilityScheduleWithRunLoop(SCNetworkReachabilityRef target, CFRunLoopRef runLoop, CFStringRef runLoopMode)
{
	SCNetworkReachabilityCallBack cb = NULL;
	void *info = NULL;

	for (int i = 0; i < g_num_reachabilities; i++) {
		if (g_reachabilities[i].target == target) {
			g_reachabilities[i].runLoop = runLoop;
			g_reachabilities[i].runLoopMode = runLoopMode;
			cb = g_reachabilities[i].callback;
			info = g_reachabilities[i].context.info;
			break;
		}
	}

	if (cb) {
		dispatch_async(dispatch_get_main_queue(), ^{
			SCNetworkReachabilityFlags flags = kSCNetworkReachabilityFlagsReachable | kSCNetworkReachabilityFlagsIsDirect;
			cb(target, flags, info);
		});
	}
	return true;
}

static nw_path_status_t
watched_nw_path_get_status(nw_path_t path)
{
	return nw_path_status_satisfied;
}

static bool
watched_nw_path_is_expensive(nw_path_t path)
{
	return false;
}

static bool
watched_nw_path_is_constrained(nw_path_t path)
{
	return false;
}

static bool
watched_nw_path_has_ipv4(nw_path_t path)
{
	return true;
}

static bool
watched_nw_path_has_dns(nw_path_t path)
{
	return true;
}

static bool
watched_nw_path_uses_interface_type(nw_path_t path, nw_interface_type_t interface_type)
{
	return (interface_type == nw_interface_type_wifi);
}

typedef struct {
	nw_path_monitor_t monitor;
	nw_path_monitor_update_handler_t update_handler;
	dispatch_queue_t queue;
	bool started;
} tracked_nw_monitor_t;

static tracked_nw_monitor_t g_nw_monitors[16];
static int g_num_nw_monitors = 0;

static void
watched_nw_path_monitor_set_queue(nw_path_monitor_t monitor, dispatch_queue_t queue)
{
	nw_path_monitor_set_queue(monitor, queue);
	for (int i = 0; i < g_num_nw_monitors; i++) {
		if (g_nw_monitors[i].monitor == monitor) {
			g_nw_monitors[i].queue = queue;
			return;
		}
	}
	if (g_num_nw_monitors < 16) {
		g_nw_monitors[g_num_nw_monitors].monitor = monitor;
		g_nw_monitors[g_num_nw_monitors].queue = queue;
		g_nw_monitors[g_num_nw_monitors].update_handler = NULL;
		g_nw_monitors[g_num_nw_monitors].started = false;
		g_num_nw_monitors++;
	}
}

static void
watched_nw_path_monitor_set_update_handler(nw_path_monitor_t monitor, nw_path_monitor_update_handler_t update_handler)
{
	nw_path_monitor_set_update_handler(monitor, update_handler);
	nw_path_monitor_update_handler_t copied = update_handler ? Block_copy(update_handler) : NULL;
	for (int i = 0; i < g_num_nw_monitors; i++) {
		if (g_nw_monitors[i].monitor == monitor) {
			if (g_nw_monitors[i].update_handler) {
				Block_release(g_nw_monitors[i].update_handler);
			}
			g_nw_monitors[i].update_handler = copied;
			if (g_nw_monitors[i].started && copied) {
				dispatch_queue_t q = g_nw_monitors[i].queue ? g_nw_monitors[i].queue : dispatch_get_main_queue();
				dispatch_async(q, ^{
					copied((nw_path_t)monitor);
				});
			}
			return;
		}
	}
	if (g_num_nw_monitors < 16) {
		g_nw_monitors[g_num_nw_monitors].monitor = monitor;
		g_nw_monitors[g_num_nw_monitors].update_handler = copied;
		g_nw_monitors[g_num_nw_monitors].queue = NULL;
		g_nw_monitors[g_num_nw_monitors].started = false;
		g_num_nw_monitors++;
	}
}

static void
watched_nw_path_monitor_start(nw_path_monitor_t monitor)
{
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: nw_path_monitor_start called\\n", who);
	say(line, (size_t)(n > 0 ? n : 0));
	nw_path_monitor_start(monitor);

	for (int i = 0; i < g_num_nw_monitors; i++) {
		if (g_nw_monitors[i].monitor == monitor) {
			g_nw_monitors[i].started = true;
			dispatch_queue_t q = g_nw_monitors[i].queue ? g_nw_monitors[i].queue : dispatch_get_main_queue();
			nw_path_monitor_update_handler_t handler = g_nw_monitors[i].update_handler;
			if (handler) {
				dispatch_async(q, ^{
					char l2[256];
					int n2 = snprintf(l2, sizeof(l2), "hakios: %s: triggering nw_path_monitor update_handler (satisfied)\\n", who);
					say(l2, (size_t)(n2 > 0 ? n2 : 0));
					handler((nw_path_t)monitor);
				});
			}
			return;
		}
	}
	if (g_num_nw_monitors < 16) {
		g_nw_monitors[g_num_nw_monitors].monitor = monitor;
		g_nw_monitors[g_num_nw_monitors].started = true;
		g_nw_monitors[g_num_nw_monitors].queue = NULL;
		g_nw_monitors[g_num_nw_monitors].update_handler = NULL;
		g_num_nw_monitors++;
	}
}

typedef struct {
	const void *ours, *theirs;
} interpose_entry_t;

__attribute__((used)) static const interpose_entry_t app_interposes[] __attribute__((section("__DATA,__interpose"))) = {
	{ (const void *)watched_spawn, (const void *)posix_spawn },
	{ (const void *)watched_SecItemCopyMatching, (const void *)SecItemCopyMatching },
	{ (const void *)watched_SecItemAdd, (const void *)SecItemAdd },
	{ (const void *)watched_SecItemUpdate, (const void *)SecItemUpdate },
	{ (const void *)watched_SecItemDelete, (const void *)SecItemDelete },
	{ (const void *)watched_SCNetworkReachabilityGetFlags, (const void *)SCNetworkReachabilityGetFlags },
	{ (const void *)watched_SCNetworkReachabilitySetCallback, (const void *)SCNetworkReachabilitySetCallback },
	{ (const void *)watched_SCNetworkReachabilitySetDispatchQueue, (const void *)SCNetworkReachabilitySetDispatchQueue },
	{ (const void *)watched_SCNetworkReachabilityScheduleWithRunLoop, (const void *)SCNetworkReachabilityScheduleWithRunLoop },
	{ (const void *)watched_nw_path_get_status, (const void *)nw_path_get_status },
	{ (const void *)watched_nw_path_is_expensive, (const void *)nw_path_is_expensive },
	{ (const void *)watched_nw_path_is_constrained, (const void *)nw_path_is_constrained },
	{ (const void *)watched_nw_path_has_ipv4, (const void *)nw_path_has_ipv4 },
	{ (const void *)watched_nw_path_has_dns, (const void *)nw_path_has_dns },
	{ (const void *)watched_nw_path_uses_interface_type, (const void *)nw_path_uses_interface_type },
	{ (const void *)watched_nw_path_monitor_set_queue, (const void *)nw_path_monitor_set_queue },
	{ (const void *)watched_nw_path_monitor_set_update_handler, (const void *)nw_path_monitor_set_update_handler },
	{ (const void *)watched_nw_path_monitor_start, (const void *)nw_path_monitor_start },
};

/* Put ours in the place of a method, keeping the one that was there. */
static void
watch(const char *name, const char *selector, IMP ours, void *theirs)
{
	Class class = objc_getClass(name);
	Method method = class != NULL ? class_getInstanceMethod(class, sel_registerName(selector)) : NULL;

	if (method != NULL && method_getImplementation(method) != ours) {
		IMP old = method_setImplementation(method, ours);
		if (theirs) *(IMP *)theirs = old;
	}
}

static void
watch_class(const char *name, const char *selector, IMP ours, void *theirs)
{
	Class class = objc_getClass(name);
	Method method = class != NULL ? class_getClassMethod(class, sel_registerName(selector)) : NULL;

	if (method != NULL && method_getImplementation(method) != ours) {
		IMP old = method_setImplementation(method, ours);
		if (theirs) *(IMP *)theirs = old;
	}
}

typedef void NSUncaughtExceptionHandler(id);

static void
hakios_uncaught_exception(id exception)
{
	id (*desc)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	const char *(*utf8)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	id name = desc ? desc(exception, sel_registerName("name")) : nil;
	id reason = desc ? desc(exception, sel_registerName("reason")) : nil;
	char line[1024];
	int n = snprintf(line, sizeof(line), "hakios: %s: UNCAUGHT EXCEPTION: %s: %s\\n", who,
		name ? utf8(name, sel_registerName("UTF8String")) : "?",
		reason ? utf8(reason, sel_registerName("UTF8String")) : "?");
	say(line, (size_t)(n > 0 ? n : 0));
}

__attribute__((constructor))
static void
hakios_app_init(void)
{
	static const int signals[] = { SIGTRAP, SIGABRT, SIGILL, SIGSEGV, SIGBUS, SIGSYS };
	struct sigaction action = { 0 };
	const char *name = getprogname();
	char line[200];
	size_t length = 0;
	int n;

	if (name == NULL) {
		return;
	}
	who = name;
	void (*set_handler)(NSUncaughtExceptionHandler *) = (void (*)(NSUncaughtExceptionHandler *))dlsym(RTLD_DEFAULT, "NSSetUncaughtExceptionHandler");
	if (set_handler) {
		set_handler(hakios_uncaught_exception);
	}
	slide = (uintptr_t)_dyld_get_shared_cache_range(&length) - CACHE_BASE;
	console = open("/dev/console", O_WRONLY);
	if (console >= 0) {
		dup2(console, 2);
	}
	action.sa_sigaction = killed;
	action.sa_flags = SA_SIGINFO | SA_NODEFER | SA_RESETHAND;
	sigemptyset(&action.sa_mask);
	for (unsigned i = 0; i < sizeof(signals) / sizeof(signals[0]); i++) {
		sigaction(signals[i], &action, NULL);
	}

	/* Load dynamic frameworks so classes can be hooked */
	dlopen("/System/Library/Frameworks/UserNotifications.framework/UserNotifications", RTLD_LAZY);
	dlopen("/System/Library/Frameworks/Contacts.framework/Contacts", RTLD_LAZY);
	dlopen("/System/Library/Frameworks/CoreLocation.framework/CoreLocation", RTLD_LAZY);
	dlopen("/System/Library/Frameworks/AppTrackingTransparency.framework/AppTrackingTransparency", RTLD_LAZY);
	dlopen("/System/Library/Frameworks/AVFoundation.framework/AVFoundation", RTLD_LAZY);
	dlopen("/System/Library/Frameworks/Photos.framework/Photos", RTLD_LAZY);

	/* Hook authorization dialogs that would otherwise hang waiting for missing system daemons */
	watch("UNUserNotificationCenter", "requestAuthorizationWithOptions:completionHandler:", (IMP)watched_un_request_auth, &orig_un_req);
	watch("UNUserNotificationCenter", "getNotificationSettingsWithCompletionHandler:", (IMP)watched_un_get_settings, NULL);
	watch("UNNotificationSettings", "authorizationStatus", (IMP)watched_un_settings_auth_status, NULL);
	watch("UNNotificationSettings", "notificationCenterSetting", (IMP)watched_un_settings_enabled, NULL);
	watch("UNNotificationSettings", "soundSetting", (IMP)watched_un_settings_enabled, NULL);
	watch("UNNotificationSettings", "badgeSetting", (IMP)watched_un_settings_enabled, NULL);
	watch("UNNotificationSettings", "alertSetting", (IMP)watched_un_settings_enabled, NULL);
	watch("UNNotificationSettings", "alertStyle", (IMP)watched_un_settings_alert_style, NULL);

	watch("CNContactStore", "requestAccessForEntityType:completionHandler:", (IMP)watched_cn_request_access, &orig_cn_req);
	watch_class("CNContactStore", "authorizationStatusForEntityType:", (IMP)watched_cn_auth_status, NULL);

	watch_class("CLLocationManager", "locationServicesEnabled", (IMP)watched_cl_location_services_enabled, NULL);
	watch_class("CLLocationManager", "authorizationStatus", (IMP)watched_cl_auth_status, NULL);
	watch("CLLocationManager", "authorizationStatus", (IMP)watched_cl_auth_status, NULL);
	watch("CLLocationManager", "accuracyAuthorization", (IMP)watched_cl_accuracy_auth, NULL);
	watch("CLLocationManager", "requestWhenInUseAuthorization", (IMP)watched_cl_request_when_in_use, NULL);
	watch("CLLocationManager", "requestAlwaysAuthorization", (IMP)watched_cl_request_always, NULL);
	watch("CLLocationManager", "startUpdatingLocation", (IMP)watched_cl_start_updating_location, NULL);

	watch_class("ATTrackingManager", "requestTrackingAuthorizationWithCompletionHandler:", (IMP)watched_att_request, NULL);
	watch_class("AVCaptureDevice", "requestAccessForMediaType:completionHandler:", (IMP)watched_av_request_access, NULL);
	watch_class("PHPhotoLibrary", "requestAuthorization:", (IMP)watched_ph_request_auth, NULL);
	watch_class("PHPhotoLibrary", "requestAuthorizationForAccessLevel:handler:", (IMP)watched_ph_request_auth_level, NULL);

	/* Watch background tasks and session tasks across all apps */
	watch("UIApplication", "beginBackgroundTaskWithExpirationHandler:", (IMP)watched_begin_task, &begin_task);
	watch("UIApplication", "beginBackgroundTaskWithName:expirationHandler:", (IMP)watched_begin_task_name, &begin_task_name);
	watch("NSURLSessionTask", "resume", (IMP)watched_resume_task, &resume_task);

	if (strcmp(name, "Instagram") == 0) {
		dispatch_async(dispatch_get_main_queue(), ^{
			watch("IGNetworkInfo", "isOnWifiNetwork", (IMP)watched_IGNetworkInfo_isOnWifiNetwork, NULL);
			watch("IGNetworkInfo", "isReachableViaWiFi", (IMP)watched_IGNetworkInfo_isReachableViaWiFi, NULL);
			watch("IGNetworkInfo", "isReachableViaWWAN", (IMP)watched_IGNetworkInfo_isReachableViaWWAN, NULL);
			watch("IGNetworkInfo", "connectionTypeString", (IMP)watched_IGNetworkInfo_connectionTypeString, NULL);
			watch("IGNetworkInfo", "fbConnectionTypeString", (IMP)watched_IGNetworkInfo_fbConnectionTypeString, NULL);
			watch("IGNetworkInfo", "networkReachabilityStatus", (IMP)watched_IGNetworkInfo_networkReachabilityStatus, NULL);

			watch("_TtC30IGSessionlessNUXTransitionView40IGSessionlessNUXTransitionViewController", "viewDidAppear:", (IMP)watched_trans_view_did_appear, &orig_trans_view_did_appear);
			watch("_TtC21IGNUXLocationServices35IGNUXLocationServicesViewController", "viewDidAppear:", (IMP)watched_loc_view_did_appear, &orig_loc_view_did_appear);

			char l2[256];
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: Instagram NUX & Network hooks registered on main queue\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
		});
	}

	if (strcmp(name, "Sileo") == 0) {
		dispatch_async(dispatch_get_main_queue(), ^{ keep_to_the_repositories(); });
		watch("NSFileManager", "moveItemAtURL:toURL:error:", (IMP)watched_move_url, &move_url);
		watch("NSFileManager", "copyItemAtURL:toURL:error:", (IMP)watched_copy_url, &copy_url);
		watch("NSFileManager", "moveItemAtPath:toPath:error:", (IMP)watched_move_path, &move_path);
		watch("NSFileManager", "copyItemAtPath:toPath:error:", (IMP)watched_copy_path, &copy_path);
	}
	n = snprintf(line, sizeof(line), "hakios: %s: started as uid %d (effective %d), watching for what kills it\\n",
	    name, (int)getuid(), (int)geteuid());
	say(line, (size_t)(n > 0 ? n : 0));
}
'''

new_text = app_text[:start_pos] + replacement
p_app.write_text(new_text, encoding='utf-8')
print("Successfully generated all CoreLocation, Push, and NUX transition hooks in inject_app.c!")
