import pathlib

p_app = pathlib.Path(r'\\wsl$\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios\userland\src\inject_app.c')
app_text = p_app.read_text(encoding='utf-8')

reg_marker = '\t\t\twatch("_TtC21IGNUXLocationServices35IGNUXLocationServicesViewController", "viewDidAppear:", (IMP)watched_loc_view_did_appear, &orig_loc_view_did_appear);'
reg_add = '''\t\t\twatch("_TtC21IGNUXLocationServices35IGNUXLocationServicesViewController", "viewDidAppear:", (IMP)watched_loc_view_did_appear, &orig_loc_view_did_appear);

\t\t\twatch("IGNUXOneTapStepController", "oneTapControllerSkipButtonTapped", (IMP)watched_onetap_skip, &orig_onetap_skip);
\t\t\twatch("IGNUXOneTapStepController", "oneTapControllerNextButtonTapped", (IMP)watched_onetap_next, &orig_onetap_next);
\t\t\twatch("IGNUXOneTapStepController", "nuxInterstitialViewDidTapSkip:", (IMP)watched_nux_interstitial_skip, &orig_nux_interstitial_skip);
\t\t\twatch("IGNUXOneTapStepController", "nuxInterstitialViewDidTapNext:", (IMP)watched_nux_interstitial_next, &orig_nux_interstitial_next);
\t\t\twatch("IGRegistrationOneTapViewController", "viewDidAppear:", (IMP)watched_reg_onetap_view_did_appear, &orig_reg_onetap_view_did_appear);
\t\t\twatch("IGRegistrationOneTapViewController", "nuxInterstitialViewDidTapSkip:", (IMP)watched_nux_interstitial_skip, &orig_nux_interstitial_skip);
\t\t\twatch("IGRegistrationOneTapViewController", "nuxInterstitialViewDidTapNext:", (IMP)watched_nux_interstitial_next, &orig_nux_interstitial_next);'''

if reg_marker in app_text and 'IGNUXOneTapStepController' not in app_text:
    app_text = app_text.replace(reg_marker, reg_add, 1)
    p_app.write_text(app_text, encoding='utf-8')
    print("Registered OneTap hooks in Instagram dispatch_async block successfully!")
else:
    print("Already registered or marker not found")
