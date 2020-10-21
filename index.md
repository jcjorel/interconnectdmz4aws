AWS Cloud customers that want to seggregate their resources at network level have a large set of options (Security Group, NACL, PrivateLink...).
As the needs become more recurrent, some use-cases can be addressed with patterns.

The *'ServerLess Interconnect DMZ Pattern for AWS'* is an automated orchestration of AWS security services to interconnnect securely environments that do not
share the same governance. Example of constraints:
* Different IP Address plan management (possibily colliding),
* Different Security rules.
* Different internal DNS structures (possible colliding).

A typical use-case is interconnecting a customer with business partners. The described solution offers a fully managed and ServerLess way to do it with standard AWS services.

![Architecture schema](https://raw.githubusercontent.com/jcjorel/interconnectdmz4aws/main/docs/schema.png)

Please visit the [project repository](https://github.com/jcjorel/interconnectdmz4aws/) for more information.
