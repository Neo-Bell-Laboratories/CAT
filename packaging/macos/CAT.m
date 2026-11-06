#import <Cocoa/Cocoa.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <stdlib.h>

static NSString *HumanSize(unsigned long long value) {
    double amount = (double)value;
    NSArray *units = @[@"B", @"KB", @"MB", @"GB", @"TB"];
    NSUInteger index = 0;
    while (amount >= 1024.0 && index + 1 < units.count) {
        amount /= 1024.0;
        index++;
    }
    return index == 0 ? [NSString stringWithFormat:@"%llu B", value]
                      : [NSString stringWithFormat:@"%.1f %@", amount, units[index]];
}

@interface CATEntry : NSObject
@property(nonatomic, copy) NSString *path;
@property(nonatomic, copy) NSString *kind;
@property(nonatomic, copy) NSString *size;
@property(nonatomic, copy) NSString *mode;
@end
@implementation CATEntry
@end

@interface CATWindow : NSObject <NSApplicationDelegate, NSTableViewDataSource, NSTableViewDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSTextField *archiveField;
@property(nonatomic, strong) NSTextField *parentField;
@property(nonatomic, strong) NSTextField *folderField;
@property(nonatomic, strong) NSTextField *statusField;
@property(nonatomic, strong) NSButton *inspectButton;
@property(nonatomic, strong) NSButton *extractButton;
@property(nonatomic, strong) NSTableView *table;
@property(nonatomic, strong) NSMutableArray<CATEntry *> *entries;
@property(nonatomic, copy) NSString *catsPath;
@end

@implementation CATWindow

- (BOOL)application:(NSApplication *)application openFile:(NSString *)filename {
    (void)application;
    self.archiveField.stringValue = filename;
    [self setDestinationForArchive:filename];
    [self inspect:nil];
    return YES;
}

- (void)application:(NSApplication *)application openFiles:(NSArray<NSString *> *)filenames {
    (void)application;
    NSString *filename = filenames.firstObject;
    if (filename) [self application:NSApp openFile:filename];
    [NSApp replyToOpenOrPrint:NSApplicationDelegateReplySuccess];
}

- (NSTextField *)label:(NSString *)text size:(CGFloat)size weight:(NSFontWeight)weight {
    NSTextField *label = [NSTextField labelWithString:text];
    label.font = [NSFont systemFontOfSize:size weight:weight];
    return label;
}

- (NSStackView *)row:(NSArray<NSView *> *)views spacing:(CGFloat)spacing {
    NSStackView *row = [[NSStackView alloc] initWithFrame:NSZeroRect];
    row.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    row.alignment = NSLayoutAttributeCenterY;
    row.spacing = spacing;
    for (NSView *view in views) [row addArrangedSubview:view];
    return row;
}

- (NSButton *)button:(NSString *)title action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.bezelStyle = NSBezelStyleRounded;
    return button;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    self.entries = [NSMutableArray array];
    NSString *resources = NSBundle.mainBundle.resourcePath;
    self.catsPath = [resources stringByAppendingPathComponent:@"cats"];
    NSRect frame = NSMakeRect(0, 0, 900, 650);
    self.window = [[NSWindow alloc] initWithContentRect:frame
        styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                   NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"CATS Archive";
    self.window.minSize = NSMakeSize(700, 500);

    NSTextField *title = [self label:@"Unarchive CATS" size:23 weight:NSFontWeightBold];
    NSTextField *subtitle = [self label:@"Inspect and safely extract a CAT archive." size:13 weight:NSFontWeightRegular];
    self.archiveField = [NSTextField textFieldWithString:@""];
    self.archiveField.placeholderString = @"Choose a .cat archive";
    NSButton *browseArchive = [self button:@"Browse…" action:@selector(chooseArchive:)];
    self.inspectButton = [self button:@"Inspect" action:@selector(inspect:)];
    NSStackView *archiveRow = [self row:@[self.archiveField, browseArchive, self.inspectButton] spacing:8];
    [self.archiveField setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
    [browseArchive setContentHuggingPriority:NSLayoutPriorityRequired forOrientation:NSLayoutConstraintOrientationHorizontal];
    [self.inspectButton setContentHuggingPriority:NSLayoutPriorityRequired forOrientation:NSLayoutConstraintOrientationHorizontal];

    NSTextField *destinationLabel = [self label:@"Extract into" size:13 weight:NSFontWeightMedium];
    self.parentField = [NSTextField textFieldWithString:NSHomeDirectory()];
    NSButton *browseParent = [self button:@"Choose location…" action:@selector(chooseParent:)];
    NSStackView *parentRow = [self row:@[self.parentField, browseParent] spacing:8];
    [self.parentField setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];

    NSTextField *folderLabel = [self label:@"New folder name" size:13 weight:NSFontWeightMedium];
    self.folderField = [NSTextField textFieldWithString:@""];
    self.folderField.placeholderString = @"Extracted archive";
    NSStackView *folderRow = [self row:@[folderLabel, self.folderField] spacing:12];
    [self.folderField setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];

    self.table = [[NSTableView alloc] initWithFrame:NSZeroRect];
    self.table.headerView = [[NSTableHeaderView alloc] initWithFrame:NSZeroRect];
    self.table.dataSource = self;
    self.table.delegate = self;
    for (NSArray *spec in @[@[@"Path", @"path", @500], @[@"Type", @"kind", @90],
                             @[@"Size", @"size", @110], @[@"Mode", @"mode", @80]]) {
        NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:spec[1]];
        column.title = spec[0];
        column.width = [spec[2] doubleValue];
        [self.table addTableColumn:column];
    }
    NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSZeroRect];
    scroll.hasVerticalScroller = YES;
    scroll.hasHorizontalScroller = YES;
    scroll.borderType = NSBezelBorder;
    scroll.documentView = self.table;

    self.statusField = [NSTextField labelWithString:@"Choose a CAT archive to inspect its contents."];
    self.statusField.lineBreakMode = NSLineBreakByTruncatingMiddle;
    self.extractButton = [self button:@"Extract" action:@selector(extract:)];
    self.extractButton.enabled = NO;
    NSStackView *footer = [self row:@[self.statusField, self.extractButton] spacing:12];
    [self.statusField setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];

    NSStackView *stack = [[NSStackView alloc] initWithFrame:NSZeroRect];
    for (NSView *view in @[
        title, subtitle, [self label:@"Archive" size:13 weight:NSFontWeightMedium], archiveRow,
        destinationLabel, parentRow, folderRow, [self label:@"Archive contents" size:13 weight:NSFontWeightMedium], scroll, footer
    ]) [stack addArrangedSubview:view];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeLeading;
    stack.spacing = 10;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    NSView *content = self.window.contentView;
    [content addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:content.leadingAnchor constant:24],
        [stack.trailingAnchor constraintEqualToAnchor:content.trailingAnchor constant:-24],
        [stack.topAnchor constraintEqualToAnchor:content.topAnchor constant:22],
        [stack.bottomAnchor constraintEqualToAnchor:content.bottomAnchor constant:-20],
        [archiveRow.widthAnchor constraintEqualToAnchor:stack.widthAnchor],
        [parentRow.widthAnchor constraintEqualToAnchor:stack.widthAnchor],
        [folderRow.widthAnchor constraintEqualToAnchor:stack.widthAnchor],
        [scroll.widthAnchor constraintEqualToAnchor:stack.widthAnchor],
        [scroll.heightAnchor constraintGreaterThanOrEqualToConstant:200],
        [scroll.heightAnchor constraintEqualToAnchor:stack.heightAnchor multiplier:0.55],
        [footer.widthAnchor constraintEqualToAnchor:stack.widthAnchor],
        [self.archiveField.heightAnchor constraintEqualToConstant:30],
        [self.parentField.heightAnchor constraintEqualToConstant:30],
        [self.folderField.heightAnchor constraintEqualToConstant:30],
    ]];
    [self.window center];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];

    NSArray<NSString *> *arguments = NSProcessInfo.processInfo.arguments;
    for (NSUInteger i = 1; i < arguments.count; i++) {
        NSString *arg = arguments[i];
        if ([arg.pathExtension.lowercaseString isEqualToString:@"cat"] || [arg.lowercaseString hasSuffix:@".cat.gz"]) {
            self.archiveField.stringValue = arg;
            [self setDestinationForArchive:arg];
            [self inspect:nil];
            break;
        }
    }
}

- (void)setDestinationForArchive:(NSString *)path {
    NSString *parent = path.stringByDeletingLastPathComponent;
    if (parent.length) self.parentField.stringValue = parent;
    NSString *name = path.lastPathComponent;
    if ([name.lowercaseString hasSuffix:@".cat.gz"]) name = [name substringToIndex:name.length - 7];
    else if ([name.lowercaseString hasSuffix:@".cat"]) name = [name substringToIndex:name.length - 4];
    if (name.length == 0) name = @"CATS Archive";
    NSString *candidate = name;
    NSUInteger suffix = 1;
    while ([[NSFileManager defaultManager] fileExistsAtPath:[parent stringByAppendingPathComponent:candidate]])
        candidate = [NSString stringWithFormat:@"%@-extracted-%lu", name, (unsigned long)suffix++];
    self.folderField.stringValue = candidate;
}

- (void)chooseArchive:(id)sender {
    (void)sender;
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.allowedFileTypes = @[@"cat", @"gz"];
    panel.canChooseFiles = YES;
    panel.canChooseDirectories = NO;
    panel.allowsMultipleSelection = NO;
    if ([panel runModal] == NSModalResponseOK && panel.URL) {
        self.archiveField.stringValue = panel.URL.path;
        [self setDestinationForArchive:panel.URL.path];
        [self inspect:nil];
    }
}

- (void)chooseParent:(id)sender {
    (void)sender;
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.canChooseFiles = NO;
    panel.canChooseDirectories = YES;
    panel.canCreateDirectories = YES;
    if ([panel runModal] == NSModalResponseOK && panel.URL) self.parentField.stringValue = panel.URL.path;
}

- (NSArray<NSString *> *)runCAT:(NSArray<NSString *> *)arguments error:(NSError **)error {
    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:self.catsPath];
    task.arguments = arguments;
    NSPipe *output = [NSPipe pipe];
    NSPipe *errors = [NSPipe pipe];
    task.standardOutput = output;
    task.standardError = errors;
    if (![task launchAndReturnError:error]) return nil;
    NSData *data = [output.fileHandleForReading readDataToEndOfFile];
    NSData *errorData = [errors.fileHandleForReading readDataToEndOfFile];
    [task waitUntilExit];
    if (task.terminationStatus != 0) {
        NSString *message = [[NSString alloc] initWithData:errorData encoding:NSUTF8StringEncoding] ?: @"CAT operation failed.";
        if (error) *error = [NSError errorWithDomain:@"CAT" code:task.terminationStatus
            userInfo:@{NSLocalizedDescriptionKey: message}];
        return nil;
    }
    NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"";
    return [text componentsSeparatedByCharactersInSet:[NSCharacterSet newlineCharacterSet]];
}

- (NSString *)decodePath:(NSString *)quoted {
    if (quoted.length < 2) return quoted;
    NSString *value = [quoted substringWithRange:NSMakeRange(1, quoted.length - 2)];
    NSMutableData *bytes = [NSMutableData data];
    const char *raw = value.UTF8String;
    for (NSUInteger i = 0; raw[i]; i++) {
        unsigned char byte = (unsigned char)raw[i];
        if (byte == '\\' && raw[i + 1]) {
            char next = raw[++i];
            if (next == 'x' && raw[i + 1] && raw[i + 2]) {
                char hex[3] = {raw[i + 1], raw[i + 2], 0};
                byte = (unsigned char)strtoul(hex, NULL, 16);
                i += 2;
            } else byte = (unsigned char)next;
        }
        [bytes appendBytes:&byte length:1];
    }
    NSString *decoded = [[NSString alloc] initWithData:bytes encoding:NSUTF8StringEncoding];
    return decoded ?: value;
}

- (void)inspect:(id)sender {
    (void)sender;
    NSString *archive = [self.archiveField.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (archive.length == 0) { [self showError:@"Choose a CAT archive first."]; return; }
    self.inspectButton.enabled = NO;
    self.extractButton.enabled = NO;
    self.statusField.stringValue = @"Validating archive…";
    [self.entries removeAllObjects];
    [self.table reloadData];
    NSError *error = nil;
    NSArray<NSString *> *lines = [self runCAT:@[@"-i", archive] error:&error];
    self.inspectButton.enabled = YES;
    if (!lines) { self.statusField.stringValue = @"Archive validation failed."; [self showError:error.localizedDescription]; return; }
    for (NSString *line in lines) {
        NSArray<NSString *> *parts = [line componentsSeparatedByString:@"\t"];
        if (parts.count < 5) continue;
        CATEntry *entry = [[CATEntry alloc] init];
        entry.kind = [parts[1] isEqualToString:@"dir"] ? @"Directory" : @"File";
        unsigned long long bytes = strtoull(parts[2].UTF8String, NULL, 10);
        entry.size = [parts[1] isEqualToString:@"dir"] ? @"" : HumanSize(bytes);
        entry.mode = parts[3];
        entry.path = [self decodePath:parts[4]];
        [self.entries addObject:entry];
    }
    [self.table reloadData];
    self.statusField.stringValue = [NSString stringWithFormat:@"Verified CAT archive · %lu entries", (unsigned long)self.entries.count];
    self.extractButton.enabled = self.entries.count > 0;
}

- (void)extract:(id)sender {
    (void)sender;
    NSString *archive = [self.archiveField.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *parent = [self.parentField.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *folder = [self.folderField.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (folder.length == 0 || [folder isEqualToString:@"."] || [folder isEqualToString:@".."] || [folder containsString:@"/"] || [folder containsString:@"\\"]) {
        [self showError:@"Choose a single folder name without path separators."]; return;
    }
    NSString *destination = [parent stringByAppendingPathComponent:folder];
    if ([[NSFileManager defaultManager] fileExistsAtPath:destination]) {
        [self showError:@"That destination folder already exists. Choose another name or location."]; return;
    }
    self.extractButton.enabled = NO;
    self.statusField.stringValue = @"Extracting archive…";
    NSError *error = nil;
    NSArray *result = [self runCAT:@[@"-d", archive, destination] error:&error];
    self.extractButton.enabled = YES;
    if (!result) { self.statusField.stringValue = @"Extraction failed."; [self showError:error.localizedDescription]; return; }
    self.statusField.stringValue = [NSString stringWithFormat:@"Extracted to %@", destination];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Archive extracted successfully.";
    alert.informativeText = destination;
    [alert addButtonWithTitle:@"Show in Finder"];
    [alert addButtonWithTitle:@"Close"];
    if ([alert runModal] == NSAlertFirstButtonReturn)
        [[NSWorkspace sharedWorkspace] selectFile:destination inFileViewerRootedAtPath:parent];
}

- (void)showError:(NSString *)message {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"CATS Archive";
    alert.informativeText = message.length ? message : @"The operation failed.";
    alert.alertStyle = NSAlertStyleCritical;
    [alert runModal];
}

- (NSInteger)numberOfRowsInTableView:(NSTableView *)tableView {
    (void)tableView;
    return self.entries.count;
}

- (id)tableView:(NSTableView *)tableView objectValueForTableColumn:(NSTableColumn *)column row:(NSInteger)row {
    (void)tableView;
    CATEntry *entry = self.entries[(NSUInteger)row];
    if ([column.identifier isEqualToString:@"path"]) return entry.path;
    if ([column.identifier isEqualToString:@"kind"]) return entry.kind;
    if ([column.identifier isEqualToString:@"size"]) return entry.size;
    return entry.mode;
}
@end

int main(int argc, const char *argv[]) {
    (void)argc; (void)argv;
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        CATWindow *delegate = [[CATWindow alloc] init];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        [app run];
    }
    return 0;
}
