import pathlib

p_app = pathlib.Path(r'\\wsl$\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios\userland\src\inject_app.c')
app_text = p_app.read_text(encoding='utf-8')

# 1. Update prepare_boot.py to disable touch_lat=1 (so log ring buffer is never flooded)
p_prep = pathlib.Path('outputs/scripts/prepare_boot.py')
prep_text = p_prep.read_text(encoding='utf-8')
if 'touch_lat=1' in prep_text:
    prep_text = prep_text.replace('touch_lat=1', 'touch_lat=0')
    p_prep.write_text(prep_text, encoding='utf-8')
    print("Disabled touch_lat in prepare_boot.py (changed to touch_lat=0)")

# 2. Patch inject_app.c
# We replace from "static unsigned long (*begin_task)(id, SEL, id);" down to end of "hakios_app_init"
start_marker = "static unsigned long (*begin_task)(id, SEL, id);"
assert start_marker in app_text, "start_marker not found"
start_pos = app_text.find(start_marker)

replacement = '''static unsigned long (*begin_task)(id, SEL, id);
static unsigned long (*begin_task_name)(id, SEL, id, id);
static void (*resume_task)(id, SEL);

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
	const char *(*utf8)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	const char *tname = task_name ? utf8(task_name, sel_registerName("UTF8String")) : "?";
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: asking UIKit for background task '%s'\\n", who, tname ? tname : "?");
	say(line, (size_t)(n > 0 ? n : 0));
	unsigned long task = begin_task_name ? begin_task_name(self, cmd, task_name, handler) : 101;
	n = snprintf(line, sizeof(line), "hakios: %s: background task '%s' is %lu\\n", who, tname ? tname : "?", task);
	say(line, (size_t)(n > 0 ? n : 0));
	return task;
}

static void
watched_resume_task(id self, SEL cmd)
{
	const char *(*string)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	id (*get)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	const char *url = "?";
	char line[700];
	id request, address, text;
	int n;

	request = get(self, sel_registerName("originalRequest"));
	address = request != NULL ? get(request, sel_registerName("URL")) : NULL;
	text = address != NULL ? get(address, sel_registerName("absoluteString")) : NULL;
	if (text != NULL) {
		url = string(text, sel_registerName("UTF8String"));
	}
	n = snprintf(line, sizeof(line), "hakios: %s: starting a session task for %s\\n", who,
	    url != NULL ? url : "?");
	say(line, (size_t)(n > 0 ? n : 0));
	if (resume_task) {
		resume_task(self, cmd);
	}
}

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
			int n2 = snprintf(l2, sizeof(l2), "hakios: %s: auto-answering CNContactStore access (false)!\\n", who);
			say(l2, (size_t)(n2 > 0 ? n2 : 0));
			block(false, NULL);
			Block_release(block);
		});
	}
}

/*
 * One setting of Sileo's, set for it at every start: "Show Packages From Canister" (ShowProvisional,
 * on by default). Canister is the search service Sileo asks about packages, and where its servers
 * cannot be reached the asking never stops -- 3810 session tasks in two minutes in one run here,
 * and the download of a package never gets its turn among them. With the setting off Sileo keeps to
 * the repositories themselves, which work. The prefix lives in memory and is new at every boot, so
 * there is nowhere to keep this but here. It is done on the main queue, not here in the library's
 * own initializer: at that point Foundation is loaded but has not run its own initializers yet, and
 * asking it for the defaults then kills the application before it says a word.
 */
static void
keep_to_the_repositories(void)
{
	id (*get)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	id (*from_text)(id, SEL, const char *) = (id (*)(id, SEL, const char *))objc_msgSend;
	void (*set_bool)(id, SEL, signed char, id) = (void (*)(id, SEL, signed char, id))objc_msgSend;
	id defaults = (id)objc_getClass("NSUserDefaults");
	id key = from_text((id)objc_getClass("NSString"), sel_registerName("stringWithUTF8String:"), "ShowProvisional");

	if (defaults == NULL || key == NULL) {
		return;
	}
	defaults = get(defaults, sel_registerName("standardUserDefaults"));
	if (defaults != NULL) {
		set_bool(defaults, sel_registerName("setBool:forKey:"), 0, key);
		say("hakios: Sileo: its Canister search is turned off (it is not reachable here)\\n", 73);
	}
}

/*
 * apt-get install, not its simulation (-s...): the one that ends in "Unable to fetch some archives"
 * when Sileo runs it and installs the package when a terminal runs the same command.
 */
static int
apt_install(char *const argv[])
{
	int install = 0;

	if (argv == NULL || argv[0] == NULL || strcmp(argv[0], "apt-get") != 0) {
		return 0;
	}
	for (int i = 1; argv[i] != NULL; i++) {
		if (argv[i][0] == '-' && argv[i][1] == 's') {
			return 0;
		}
		install |= strcmp(argv[i], "install") == 0;
	}
	return install;
}

/*
 * What apt says goes to Sileo, which shows a line of it at most. Run the same apt-get, with the same
 * descriptors, credential and environment, under a shell that first says on the console who it runs
 * as, what lies in apt's archives and what Sileo's index says of the package, and afterwards how apt
 * ended and what the archives hold then. This is how "Unable to fetch some archives" was found: the
 * archives were empty, Sileo's /bin/mv having never run.
 */
static int
spawn_apt_said(pid_t *pid, const posix_spawn_file_actions_t *actions, const posix_spawnattr_t *attr,
    char *const argv[], char *const envp[])
{
	static char script[] =
	    "exec 7>/dev/console; J=/var/jb\\n"
	    "echo \\"hakios: apt-get runs as $($J/usr/bin/id), in $(pwd)\\" >&7\\n"
	    "$J/bin/ls -ln $J/var/cache/apt/archives $J/var/lib/apt/sileolists >&7 2>&1\\n"
	    "for a in \\"$@\\"; do case $a in -*|install) ;; *) p=${a%%=*}\\n"
	    "  echo \\"hakios: $p in sileolists:\\" >&7\\n"
	    "  $J/usr/bin/grep -h -A30 \\"^Package: $p\\\\$\\" $J/var/lib/apt/sileolists/*Packages 2>&1 | $J/usr/bin/head -40 >&7 ;; esac; done\\n"
	    "$J/usr/bin/apt-get \\"$@\\"\\n"
	    "s=$?; echo \\"hakios: apt-get exits $s; its archives after:\\" >&7\\n"
	    "$J/bin/ls -ln $J/var/cache/apt/archives >&7 2>&1; exit $s\\n";
	char *wrapped[96];
	int k = 0;

	for (int i = 0; envp != NULL && envp[i] != NULL; i++) {
		char line[600];
		int n = snprintf(line, sizeof(line), "hakios: %s: apt-get's environment: %s\\n", who, envp[i]);

		say(line, (size_t)(n < (int)sizeof(line) ? n : (int)sizeof(line) - 1));
	}
	wrapped[k++] = "sh";
	wrapped[k++] = "-c";
	wrapped[k++] = script;
	wrapped[k++] = "apt-get";
	for (int i = 1; argv[i] != NULL && k < 95; i++) {
		wrapped[k++] = argv[i];
	}
	wrapped[k] = NULL;
	return posix_spawn(pid, "/var/jb/bin/sh", actions, attr, wrapped, envp);
}

/*
 * Every program the application starts, with its arguments. Sileo does everything to the system by
 * spawning its set-user-ID helper, which execs apt or dpkg; the arguments are the whole question
 * when apt's answer to Sileo differs from apt's answer on the command line.
 */
static int
watched_spawn(pid_t *pid, const char *path, const posix_spawn_file_actions_t *actions,
    const posix_spawnattr_t *attr, char *const argv[], char *const envp[])
{
	char line[1200];
	int n = snprintf(line, sizeof(line), "hakios: %s: (uid %d) spawns %s", who, (int)getuid(),
	    path != NULL ? path : "?");

	for (int i = 0; argv != NULL && argv[i] != NULL && n < (int)sizeof(line) - 40; i++) {
		n += snprintf(line + n, sizeof(line) - (size_t)n, " %s", argv[i]);
	}
	/*
	 * The size of what it is about to move, while the file is still there: apt refuses the
	 * package Sileo puts in its archives ("Unable to fetch some archives") and takes the very
	 * same package when apt itself fetched it, so the first thing to know is whether the file
	 * is whole.
	 */
	if (argv != NULL && argv[0] != NULL && strcmp(argv[0], "mv") == 0 && argv[1] != NULL) {
		struct stat st;

		if (stat(argv[1], &st) == 0) {
			n += snprintf(line + n, sizeof(line) - (size_t)n, " [%lld bytes]", (long long)st.st_size);
		} else {
			n += snprintf(line + n, sizeof(line) - (size_t)n, " [no such file]");
		}
	}
	n += snprintf(line + n, sizeof(line) - (size_t)n, "\\n");
	say(line, (size_t)n);
	if (apt_install(argv)) {
		return spawn_apt_said(pid, actions, attr, argv, envp);
	}
	n = posix_spawn(pid, path, actions, attr, argv, envp);
	if (n != 0) {
		char said[300];
		int k = snprintf(said, sizeof(said), "hakios: %s: ... and that spawn failed: %s\\n", who, strerror(n));

		say(said, (size_t)(k < (int)sizeof(said) ? k : (int)sizeof(said) - 1));
	}
	return n;
}

/*
 * A file the application moves or copies itself (NSFileManager, under Swift's FileManager), when it
 * fails: from where, to where, and what the error says. Sileo moves each download into place this
 * way, and says only "The operation couldn't be completed. No such file or directory".
 */
static const char *
text_of(id object)
{
	id (*get)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
	const char *(*utf8)(id, SEL) = (const char *(*)(id, SEL))objc_msgSend;
	id text;

	if (object == NULL) {
		return "(nil)";
	}
	text = (class_respondsToSelector(object_getClass(object), sel_registerName("path")) ?
	    get(object, sel_registerName("path")) : get(object, sel_registerName("description")));
	return text != NULL ? utf8(text, sel_registerName("UTF8String")) : "?";
}

static signed char (*move_url)(id, SEL, id, id, id *), (*copy_url)(id, SEL, id, id, id *);
static signed char (*move_path)(id, SEL, id, id, id *), (*copy_path)(id, SEL, id, id, id *);

static signed char
file_said(const char *what, signed char ok, id from, id to, id error)
{
	if (!ok) {
		char line[1400];
		int n = snprintf(line, sizeof(line), "hakios: %s: %s %s -> %s failed: %s\\n", who, what, text_of(from),
		    text_of(to), error != NULL ? text_of(error) : "(no error given)");

		say(line, (size_t)(n < (int)sizeof(line) ? n : (int)sizeof(line) - 1));
	}
	return ok;
}

static signed char
watched_move_url(id self, SEL cmd, id from, id to, id *error)
{
	id mine = NULL;
	signed char ok = move_url(self, cmd, from, to, error != NULL ? error : &mine);

	return file_said("moveItemAtURL", ok, from, to, error != NULL ? *error : mine);
}

static signed char
watched_copy_url(id self, SEL cmd, id from, id to, id *error)
{
	id mine = NULL;
	signed char ok = copy_url(self, cmd, from, to, error != NULL ? error : &mine);

	return file_said("copyItemAtURL", ok, from, to, error != NULL ? *error : mine);
}

static signed char
watched_move_path(id self, SEL cmd, id from, id to, id *error)
{
	id mine = NULL;
	signed char ok = move_path(self, cmd, from, to, error != NULL ? error : &mine);

	return file_said("moveItemAtPath", ok, from, to, error != NULL ? *error : mine);
}

static signed char
watched_copy_path(id self, SEL cmd, id from, id to, id *error)
{
	id mine = NULL;
	signed char ok = copy_path(self, cmd, from, to, error != NULL ? error : &mine);

	return file_said("copyItemAtPath", ok, from, to, error != NULL ? *error : mine);
}

static CFMutableArrayRef g_keychain_cache = NULL;

static void
cfstring_to_utf8(CFStringRef str, char *buf, size_t buflen)
{
	if (!str || buflen == 0) {
		if (buflen > 0) buf[0] = '\\0';
		return;
	}
	if (!CFStringGetCString(str, buf, (CFIndex)buflen, kCFStringEncodingUTF8)) {
		buf[0] = '\\0';
	}
}

static void
save_keychain_cache(void)
{
	if (!g_keychain_cache) {
		return;
	}
	mkdir("/private/var/mobile", 0755);
	mkdir("/private/var/mobile/Library", 0755);
	CFDataRef data = CFPropertyListCreateData(kCFAllocatorDefault, (CFPropertyListRef)g_keychain_cache,
	    kCFPropertyListBinaryFormat_v1_0, 0, NULL);
	if (!data) {
		data = CFPropertyListCreateData(kCFAllocatorDefault, (CFPropertyListRef)g_keychain_cache,
		    kCFPropertyListXMLFormat_v1_0, 0, NULL);
	}
	if (data) {
		const UInt8 *bytes = CFDataGetBytePtr(data);
		CFIndex len = CFDataGetLength(data);
		int fd = open("/private/var/mobile/Library/KeychainFallback.plist.tmp", O_WRONLY | O_CREAT | O_TRUNC, 0644);
		if (fd >= 0) {
			(void)write(fd, bytes, (size_t)len);
			close(fd);
			rename("/private/var/mobile/Library/KeychainFallback.plist.tmp",
			    "/private/var/mobile/Library/KeychainFallback.plist");
		}
		CFRelease(data);
	}
}

static void
init_keychain_cache(void)
{
	if (g_keychain_cache) {
		return;
	}
	int fd = open("/private/var/mobile/Library/KeychainFallback.plist", O_RDONLY);
	if (fd >= 0) {
		struct stat st;
		if (fstat(fd, &st) == 0 && st.st_size > 0) {
			void *buf = malloc((size_t)st.st_size);
			if (buf) {
				ssize_t rd = read(fd, buf, (size_t)st.st_size);
				if (rd > 0) {
					CFDataRef data = CFDataCreateWithBytesNoCopy(kCFAllocatorDefault, (const UInt8 *)buf, rd, kCFAllocatorMalloc);
					if (data) {
						CFPropertyListRef plist = CFPropertyListCreateWithData(kCFAllocatorDefault, data,
						    kCFPropertyListMutableContainersAndLeaves, NULL, NULL);
						CFRelease(data);
						if (plist && CFGetTypeID(plist) == CFArrayGetTypeID()) {
							g_keychain_cache = (CFMutableArrayRef)plist;
						} else if (plist) {
							CFRelease(plist);
						}
					}
				} else {
					free(buf);
				}
			}
		}
		close(fd);
	}
	if (!g_keychain_cache) {
		g_keychain_cache = CFArrayCreateMutable(kCFAllocatorDefault, 0, &kCFTypeArrayCallBacks);
	}
}

static CFDataRef
make_persistent_ref(CFDictionaryRef item)
{
	CFStringRef svc = (CFStringRef)CFDictionaryGetValue(item, kSecAttrService);
	if (!svc) {
		svc = (CFStringRef)CFDictionaryGetValue(item, kSecAttrServer);
	}
	CFStringRef acc = (CFStringRef)CFDictionaryGetValue(item, kSecAttrAccount);
	char s_svc[128] = {0};
	char s_acc[128] = {0};
	cfstring_to_utf8(svc, s_svc, sizeof(s_svc));
	cfstring_to_utf8(acc, s_acc, sizeof(s_acc));
	char ref_str[300];
	int n = snprintf(ref_str, sizeof(ref_str), "pref:%s:%s", s_svc, s_acc);
	return CFDataCreate(kCFAllocatorDefault, (const UInt8 *)ref_str, (CFIndex)(n > 0 ? n : 0));
}

static Boolean
item_matches_query(CFDictionaryRef item, CFDictionaryRef query)
{
	if (!query) {
		return true;
	}
	CFDataRef q_pref = (CFDataRef)CFDictionaryGetValue(query, kSecValuePersistentRef);
	if (q_pref) {
		CFDataRef i_pref = make_persistent_ref(item);
		Boolean match = CFEqual(q_pref, i_pref);
		CFRelease(i_pref);
		return match;
	}

	CFTypeRef q_class = CFDictionaryGetValue(query, kSecClass);
	if (q_class) {
		CFTypeRef i_class = CFDictionaryGetValue(item, kSecClass);
		if (!i_class || !CFEqual(q_class, i_class)) {
			return false;
		}
	}

	CFTypeRef q_service = CFDictionaryGetValue(query, kSecAttrService);
	if (q_service) {
		CFTypeRef i_service = CFDictionaryGetValue(item, kSecAttrService);
		if (!i_service || !CFEqual(q_service, i_service)) {
			return false;
		}
	}

	CFTypeRef q_account = CFDictionaryGetValue(query, kSecAttrAccount);
	if (q_account) {
		CFTypeRef i_account = CFDictionaryGetValue(item, kSecAttrAccount);
		if (!i_account || !CFEqual(q_account, i_account)) {
			return false;
		}
	}

	CFTypeRef q_server = CFDictionaryGetValue(query, kSecAttrServer);
	if (q_server) {
		CFTypeRef i_server = CFDictionaryGetValue(item, kSecAttrServer);
		if (!i_server || !CFEqual(q_server, i_server)) {
			return false;
		}
	}

	CFTypeRef q_group = CFDictionaryGetValue(query, kSecAttrAccessGroup);
	if (q_group) {
		CFTypeRef i_group = CFDictionaryGetValue(item, kSecAttrAccessGroup);
		if (!i_group || !CFEqual(q_group, i_group)) {
			return false;
		}
	}

	return true;
}

static CFTypeRef
build_query_result_item(CFDictionaryRef item, CFDictionaryRef query)
{
	Boolean return_data = query && CFDictionaryGetValue(query, kSecReturnData) == kCFBooleanTrue;
	Boolean return_attrs = query && CFDictionaryGetValue(query, kSecReturnAttributes) == kCFBooleanTrue;
	Boolean return_pref = query && CFDictionaryGetValue(query, kSecReturnPersistentRef) == kCFBooleanTrue;

	if (return_data && return_attrs) {
		return CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, item);
	}
	if (return_data) {
		CFTypeRef data = CFDictionaryGetValue(item, kSecValueData);
		if (data) {
			return CFRetain(data);
		}
		const UInt8 empty = 0;
		return CFDataCreate(kCFAllocatorDefault, &empty, 0);
	}
	if (return_attrs) {
		CFMutableDictionaryRef copy = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, item);
		if (copy) {
			CFDictionaryRemoveValue(copy, kSecValueData);
		}
		return copy;
	}
	if (return_pref) {
		return make_persistent_ref(item);
	}
	return CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, item);
}

static void
apply_dict_entry(const void *key, const void *val, void *context)
{
	CFMutableDictionaryRef target = (CFMutableDictionaryRef)context;
	CFDictionarySetValue(target, key, val);
}

static void
log_dict(const char *prefix, CFDictionaryRef dict)
{
	char line[512];
	char s_svc[128] = {0}, s_acc[128] = {0}, s_class[64] = {0};
	if (!dict) {
		int n = snprintf(line, sizeof(line), "hakios: %s: %s (null)\\n", who, prefix);
		say(line, (size_t)(n > 0 ? n : 0));
		return;
	}
	CFStringRef svc = (CFStringRef)CFDictionaryGetValue(dict, kSecAttrService);
	if (!svc) {
		svc = (CFStringRef)CFDictionaryGetValue(dict, kSecAttrServer);
	}
	CFStringRef acc = (CFStringRef)CFDictionaryGetValue(dict, kSecAttrAccount);
	CFStringRef cls = (CFStringRef)CFDictionaryGetValue(dict, kSecClass);
	cfstring_to_utf8(svc, s_svc, sizeof(s_svc));
	cfstring_to_utf8(acc, s_acc, sizeof(s_acc));
	cfstring_to_utf8(cls, s_class, sizeof(s_class));
	int n = snprintf(line, sizeof(line), "hakios: %s: %s cls=%s svc/srvr='%s' acc='%s'\\n",
	    who, prefix, s_class, s_svc, s_acc);
	say(line, (size_t)(n > 0 ? n : 0));
}

static OSStatus
watched_SecItemCopyMatching(CFDictionaryRef query, CFTypeRef *result)
{
	OSStatus status = SecItemCopyMatching(query, result);
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemCopyMatching returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));
	log_dict("SecItemCopyMatching query:", query);

	if (status != errSecSuccess) {
		init_keychain_cache();
		Boolean match_all = false;
		if (query) {
			CFTypeRef limit = CFDictionaryGetValue(query, kSecMatchLimit);
			if (limit && (CFEqual(limit, kSecMatchLimitAll) || CFGetTypeID(limit) == CFNumberGetTypeID())) {
				match_all = true;
			}
		}

		Boolean has_return = (query && (
			CFDictionaryGetValue(query, kSecReturnData) == kCFBooleanTrue ||
			CFDictionaryGetValue(query, kSecReturnAttributes) == kCFBooleanTrue ||
			CFDictionaryGetValue(query, kSecReturnPersistentRef) == kCFBooleanTrue ||
			CFDictionaryGetValue(query, kSecReturnRef) == kCFBooleanTrue
		));

		CFIndex count = CFArrayGetCount(g_keychain_cache);
		if (match_all) {
			CFMutableArrayRef matches = CFArrayCreateMutable(kCFAllocatorDefault, 0, &kCFTypeArrayCallBacks);
			for (CFIndex i = 0; i < count; i++) {
				CFDictionaryRef item = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
				if (item_matches_query(item, query)) {
					if (has_return) {
						CFTypeRef res = build_query_result_item(item, query);
						if (res) {
							CFArrayAppendValue(matches, res);
							CFRelease(res);
						}
					} else {
						CFArrayAppendValue(matches, item);
					}
				}
			}
			if (CFArrayGetCount(matches) > 0) {
				if (result) {
					if (has_return) {
						*result = matches;
					} else {
						*result = NULL;
						CFRelease(matches);
					}
				} else {
					CFRelease(matches);
				}
				n = snprintf(line, sizeof(line), "hakios: %s: SecItemCopyMatching resolved %ld items from persistent fallback!\\n",
				    who, CFArrayGetCount(matches));
				say(line, (size_t)(n > 0 ? n : 0));
				return errSecSuccess;
			}
			CFRelease(matches);
			return -25300;
		} else {
			for (CFIndex i = 0; i < count; i++) {
				CFDictionaryRef item = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
				if (item_matches_query(item, query)) {
					if (result) {
						if (has_return) {
							*result = build_query_result_item(item, query);
						} else {
							*result = NULL;
						}
					}
					n = snprintf(line, sizeof(line), "hakios: %s: SecItemCopyMatching resolved 1 item from persistent fallback!\\n", who);
					say(line, (size_t)(n > 0 ? n : 0));
					return errSecSuccess;
				}
			}
			return -25300;
		}
	}
	return status;
}

static OSStatus
watched_SecItemAdd(CFDictionaryRef attributes, CFTypeRef *result)
{
	OSStatus status = SecItemAdd(attributes, result);
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemAdd returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));
	log_dict("SecItemAdd attributes:", attributes);

	if (status != errSecSuccess) {
		init_keychain_cache();
		if (attributes) {
			CFIndex count = CFArrayGetCount(g_keychain_cache);
			CFIndex existing_idx = -1;
			for (CFIndex i = 0; i < count; i++) {
				CFDictionaryRef item = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
				if (item_matches_query(item, attributes)) {
					existing_idx = i;
					break;
				}
			}

			CFMutableDictionaryRef copy = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, attributes);
			if (copy) {
				if (existing_idx >= 0) {
					CFArraySetValueAtIndex(g_keychain_cache, existing_idx, copy);
				} else {
					CFArrayAppendValue(g_keychain_cache, copy);
				}
				save_keychain_cache();

				Boolean has_return = (
					CFDictionaryGetValue(attributes, kSecReturnData) == kCFBooleanTrue ||
					CFDictionaryGetValue(attributes, kSecReturnAttributes) == kCFBooleanTrue ||
					CFDictionaryGetValue(attributes, kSecReturnPersistentRef) == kCFBooleanTrue ||
					CFDictionaryGetValue(attributes, kSecReturnRef) == kCFBooleanTrue
				);

				if (result) {
					if (has_return) {
						*result = build_query_result_item(copy, attributes);
					} else {
						*result = NULL;
					}
				}
				CFRelease(copy);
			}
		}
		n = snprintf(line, sizeof(line), "hakios: %s: SecItemAdd saved to persistent fallback cache!\\n", who);
		say(line, (size_t)(n > 0 ? n : 0));
		return errSecSuccess;
	}
	return status;
}

static OSStatus
watched_SecItemUpdate(CFDictionaryRef query, CFDictionaryRef attributesToUpdate)
{
	OSStatus status = SecItemUpdate(query, attributesToUpdate);
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemUpdate returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));

	if (status != errSecSuccess) {
		init_keychain_cache();
		CFIndex count = CFArrayGetCount(g_keychain_cache);
		Boolean updated = false;
		for (CFIndex i = 0; i < count; i++) {
			CFDictionaryRef item = (CFDictionaryRef)CFArrayGetValueAtIndex(g_keychain_cache, i);
			if (item_matches_query(item, query)) {
				CFMutableDictionaryRef copy = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, item);
				if (copy) {
					if (attributesToUpdate) {
						CFDictionaryApplyFunction(attributesToUpdate, (CFDictionaryApplierFunction)apply_dict_entry, copy);
					}
					CFArraySetValueAtIndex(g_keychain_cache, i, copy);
					CFRelease(copy);
					updated = true;
				}
			}
		}
		if (updated) {
			save_keychain_cache();
			n = snprintf(line, sizeof(line), "hakios: %s: SecItemUpdate updated item in persistent fallback cache!\\n", who);
			say(line, (size_t)(n > 0 ? n : 0));
			return errSecSuccess;
		}

		/*
		 * Upsert: if query had no existing item in the cache, combine query + attributesToUpdate
		 * and insert it so the update operation succeeds and never blocks app progress!
		 */
		CFMutableDictionaryRef new_item = query ? CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, query) :
		    CFDictionaryCreateMutable(kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
		if (new_item) {
			if (attributesToUpdate) {
				CFDictionaryApplyFunction(attributesToUpdate, (CFDictionaryApplierFunction)apply_dict_entry, new_item);
			}
			CFArrayAppendValue(g_keychain_cache, new_item);
			save_keychain_cache();
			CFRelease(new_item);
			n = snprintf(line, sizeof(line), "hakios: %s: SecItemUpdate upserted new item into persistent fallback cache!\\n", who);
			say(line, (size_t)(n > 0 ? n : 0));
			return errSecSuccess;
		}
		return errSecSuccess;
	}
	return status;
}

static OSStatus
watched_SecItemDelete(CFDictionaryRef query)
{
	OSStatus status = SecItemDelete(query);
	char line[256];
	int n = snprintf(line, sizeof(line), "hakios: %s: SecItemDelete returned %d\\n", who, (int)status);
	say(line, (size_t)(n > 0 ? n : 0));

	if (status != errSecSuccess) {
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
		} else {
			n = snprintf(line, sizeof(line), "hakios: %s: SecItemDelete item was not found (treating as success)\\n", who);
			say(line, (size_t)(n > 0 ? n : 0));
		}
		return errSecSuccess;
	}
	return status;
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
};

/* Put ours in the place of a method, keeping the one that was there. */
static void
watch(const char *name, const char *selector, IMP ours, void *theirs)
{
	Class class = objc_getClass(name);
	Method method = class != NULL ? class_getInstanceMethod(class, sel_registerName(selector)) : NULL;

	if (method != NULL && method_getImplementation(method) != ours) {
		*(IMP *)theirs = method_setImplementation(method, ours);
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
	/*
	 * An application's standard error goes nowhere here, and that is where the Swift runtime says
	 * what it is about to die of ("Fatal error: ..."), so it is pointed at the console.
	 */
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

	/* Load dynamic frameworks if not already loaded so classes can be hooked */
	dlopen("/System/Library/Frameworks/UserNotifications.framework/UserNotifications", RTLD_LAZY);
	dlopen("/System/Library/Frameworks/Contacts.framework/Contacts", RTLD_LAZY);

	/* Hook authorization dialogs that would otherwise hang waiting for missing system daemons */
	watch("UNUserNotificationCenter", "requestAuthorizationWithOptions:completionHandler:", (IMP)watched_un_request_auth, &orig_un_req);
	watch("CNContactStore", "requestAccessForEntityType:completionHandler:", (IMP)watched_cn_request_access, &orig_cn_req);

	/* Watch background tasks and session tasks across all apps */
	watch("UIApplication", "beginBackgroundTaskWithExpirationHandler:", (IMP)watched_begin_task, &begin_task);
	watch("UIApplication", "beginBackgroundTaskWithName:expirationHandler:", (IMP)watched_begin_task_name, &begin_task_name);
	watch("NSURLSessionTask", "resume", (IMP)watched_resume_task, &resume_task);

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
print("inject_app.c successfully updated!")
