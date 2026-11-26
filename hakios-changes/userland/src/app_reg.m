#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("usage: app_reg path/to/App.app\n");
        return 1;
    }
    @autoreleasepool {
        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSURL *url = [NSURL fileURLWithPath:path isDirectory:YES];
        
        Class workspaceClass = objc_getClass("LSApplicationWorkspace");
        if (!workspaceClass) {
            printf("Error: LSApplicationWorkspace not found\n");
            return 1;
        }
        
        id workspace = ((id (*)(id, SEL))objc_msgSend)((id)workspaceClass, sel_registerName("defaultWorkspace"));
        if (!workspace) {
            printf("Error: defaultWorkspace is nil\n");
            return 1;
        }
        
        SEL regSel = sel_registerName("registerApplication:");
        if ([workspace respondsToSelector:regSel]) {
            BOOL res = ((BOOL (*)(id, SEL, id))objc_msgSend)(workspace, regSel, url);
            printf("registerApplication(%s): %s\n", [path UTF8String], res ? "OK" : "FAIL");
        } else {
            printf("LSApplicationWorkspace does not respond to registerApplication:\n");
        }
        
        SEL regDict = sel_registerName("registerApplicationDictionary:");
        if ([workspace respondsToSelector:regDict]) {
            NSString *plistPath = [path stringByAppendingPathComponent:@"Info.plist"];
            NSDictionary *dict = [NSDictionary dictionaryWithContentsOfFile:plistPath];
            if (dict) {
                BOOL res = ((BOOL (*)(id, SEL, id))objc_msgSend)(workspace, regDict, dict);
                printf("registerApplicationDictionary(%s): %s\n", [path UTF8String], res ? "OK" : "FAIL");
            }
        }
    }
    return 0;
}
